"""ESPEI 参数优化引擎（纯 Python，不依赖 PyQt6）。

把 ESPEI 的三种玩法收敛成一个入口 :func:`run_espei`，供 UI 层丢进后台线程：

=============  ==========================================================
模式            说明
=============  ==========================================================
``generate``   单步参数生成：线性回归出一套 CALPHAD 参数，直接得到新 TDB
``mcmc``       MCMC 拟合：在已有参数库上做贝叶斯采样，产出最优参数集
``check``      只检查数据集是否合法，不训练、不出库
=============  ==========================================================

设计要点
--------
* **只调用 ESPEI 的公开入口** ``espei.espei_script.run_espei``，不复制它的
  参数装配逻辑，避免与上游 schema 漂移。
* 参数校验交给 ESPEI 自己的 ``get_run_settings``（cerberus schema），
  这样"界面上填错"和"命令行填错"报的是同一套错。
* **进度与日志**：ESPEI 把日志写进 **root logger**（``espei.logger`` 里的
  ``config_logger`` 会 ``handlers.clear()``）。因此这里在调用前临时替换
  ``espei.logger.config_logger``，在其清完 handler 之后再挂上自己的捕获 handler
  （``espei/espei_script.py:147`` 是通过 ``espei.logger.config_logger`` 属性访问的，
  替换能被 ``run_espei`` 看见）。否则 ESPEI 的运行日志全部丢给 stderr，界面一片空白。
* 输出 TDB 由 ESPEI 自己落盘（``dbf.to_file(output_db, if_exists='overwrite')``），
  引擎只负责定位文件并统计数据集数量。
"""
from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .diagnostics import CalculationError, diagnose, log_exception
from ..config import DEFAULT_OUTPUT_DB, ESPEI_DATA_WEIGHTS

#: 进度回调类型：callable(已完成, 总数, 提示文本)
ProgressCB = Optional[Callable[[int, int, str], None]]

#: ESPEI 默认使用的模型拟合描述（全限定导入路径）
DEFAULT_FITTING_DESCRIPTION = (
    "espei.parameter_selection.fitting_descriptions.gibbs_energy_fitting_description"
)

logger = logging.getLogger(__name__)


class _LogCapture(logging.Handler):
    """把 ESPEI 的日志流转发给进度回调。

    回调可能来自后台线程，这里只做**入队**，不做任何 Qt 相关的操作，
    由 UI 侧的信号机制自动跨线程排队（Qt 的 signal/slot 默认 QueuedConnection）。
    """

    #: 最近捕获的日志行（上限 :data:`MAX_LOG_LINES`），供界面展示
    lines: List[str] = []
    #: 日志行的上限：ESPEI 一轮 MCMC 能刷几千行，全留会拖垮界面
    MAX_LOG_LINES = 300

    def __init__(self, sink: Optional[Callable[[str], None]] = None) -> None:
        super().__init__(level=logging.NOTSET)
        self._sink = sink
        self.lines = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003 - logging.Logger.emit
        try:
            text = self.format(record)[:400]
        except Exception:  # pragma: no cover - 格式化失败不应打断计算
            return
        self.lines.append(text)
        if len(self.lines) > self.MAX_LOG_LINES:
            del self.lines[: len(self.lines) - self.MAX_LOG_LINES]
        if self._sink is None:
            return
        try:
            self._sink(text)
        except Exception:  # pragma: no cover - 回调异常不影响 ESPEI
            pass


#: 当前挂到 root logger 上的捕获 handler。ESPEI 的 config_logger 会清空
#: root handler，所以必须在它清完之后再把捕获 handler 加回去。
_ACTIVE_CAPTURE: Optional[_LogCapture] = None
#: 被替换前的 ESPEI 原版 config_logger
_ORIGINAL_CONFIG_LOGGER: Any = None


def _config_logger_with_capture(verbosity: int = 0, filename=None,
                                reset_handlers: bool = True):
    """模块级钩子：先按 ESPEI 原逻辑配置日志，再补上 UI 的捕获 handler。

    必须是模块级函数而不是 ``run_espei`` 里的闭包——MCMC 走 dask 时会把
    logging 相关对象 pickle 到 worker 进程，局部函数无法序列化，
    会直接报 ``Can't get local object`` / ``cannot pickle RLock``。
    """
    original = _ORIGINAL_CONFIG_LOGGER
    if original is None:
        # dask worker 是独立进程：模块全局还没被 run_espei 赋值，
        # 那里的 espei.logger.config_logger 仍是未打补丁的原版
        import espei.logger as _espei_logger

        original = _espei_logger.config_logger
    result = original(
        verbosity=verbosity, filename=filename, reset_handlers=reset_handlers
    )
    if _ACTIVE_CAPTURE is not None:
        logging.getLogger().addHandler(_ACTIVE_CAPTURE)
    return result


@dataclass
class EspeiSettings:
    """ESPEI 的一次运行配置。所有字段都是"用户从界面上填的东西"。"""

    mode: str = "generate"
    #: phase_models 的 JSON 路径（schema 要求以 .json 结尾）
    phase_models: str = ""
    #: 数据集目录（里面是若干 .json 数据集）
    datasets: str = ""
    #: 起始 TDB；generate 模式下可选，mcmc 模式下必填
    input_db: str = ""
    #: ESPEI 写出的 TDB 路径（相对路径会落到工作目录，界面上会换成绝对路径）
    output_db: str = DEFAULT_OUTPUT_DB
    #: 参考态
    ref_state: str = "SGTE91"
    #: 多余自由能模型，ESPEI schema 目前只接受 "linear"
    excess_model: str = "linear"
    #: 岭回归系数；None 表示普通最小二乘
    ridge_alpha: Optional[float] = None
    #: system.tags：按数据集里的 tags 名统一追加排除项 / 权重
    tags: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: generate_parameters.aicc_penalty_factor：按相覆盖 AICc 惩罚倍数
    aicc_penalty_factor: Optional[Dict[str, Dict[str, float]]] = None
    #: 输出目录，ESPEI 的 log / trace / prob 都落在工作目录里
    output_dir: str = ""
    #: 日志详细级别 0~3
    verbosity: int = 1
    #: ---- 仅 mcmc 模式 ----
    iterations: int = 100
    save_interval: int = 1
    chains_per_parameter: int = 2
    chain_std_deviation: float = 0.1
    #: dask / none（none 表示单核串行，与官方教程一致）
    scheduler: str = "dask"
    cores: int = 1
    prior: str = "zero"
    #: normal 先验的位置 / 尺度（相对当前参数值），与官方 Cu-Mg 示例一致
    prior_loc_relative: Optional[float] = None
    prior_scale_relative: Optional[float] = None
    #: 各类数据的权重，键必须是 ZPF/ACR/HM/SM/CPM 的子集
    data_weights: Dict[str, float] = field(default_factory=dict)

    def validate(self) -> None:
        """在把配置交给 ESPEI 之前做一轮**廉价**的本地检查。

        ESPEI 自己的 schema 校验会在运行到一半时才报，界面上等几十秒才弹错体验很差。
        这里只查"文件是否存在"这类不依赖 ESPEI 的问题。
        """
        if self.mode == "check":
            if not self.datasets:
                raise CalculationError("请指定数据集目录", "ESPEI 用 *.json 数据集训练，目录里至少要有一个文件")
            return
        if not self.phase_models:
            raise CalculationError("请指定 phase_models 文件", "ESPEI 需要一个描述 CALPHAD 相模型的 .json")
        if not self.datasets:
            raise CalculationError("请指定数据集目录", "里面应包含若干 ESPEI 格式的 .json 数据集")
        phase_models_path = Path(self.phase_models)
        if not phase_models_path.is_file():
            raise CalculationError(
                f"找不到 phase_models 文件：{phase_models_path.name}",
                f"完整路径：{phase_models_path}",
            )
        if not Path(self.datasets).is_dir():
            raise CalculationError(
                f"找不到数据集目录：{self.datasets}",
                "ESPEI 在数据集目录里递归搜索 *.json",
            )
        if not list_datasets(self.datasets):
            raise CalculationError(
                "数据集目录里没有找到任何 .json 数据集",
                "ESPEI 在数据目录中递归搜索 *.json，请确认选的是目录而不是单个文件",
            )
        if self.mode == "mcmc":
            if not self.input_db:
                raise CalculationError("MCMC 需要一个起始数据库", "请填写 input_db（上一轮 generate 产出的 TDB）")
            if not Path(self.input_db).is_file():
                raise CalculationError(f"找不到起始数据库：{Path(self.input_db).name}", str(self.input_db))
            if self.iterations <= 0:
                raise CalculationError("MCMC 迭代次数必须大于 0", "典型值 100 ~ 20000")


@dataclass
class EspeiResult:
    """一次 ESPEI 运行的产物。"""

    mode: str
    elapsed_s: float
    #: 模式不是 check 时才有内容
    database: Any = None
    #: ESPEI 实际写出的 TDB 路径（check 模式为 None）
    output_db: Optional[Path] = None
    #: 载入的数据集数量
    n_datasets: int = 0
    #: 捕获到的 ESPEI 日志（最近 N 条，供界面展示）
    log_lines: List[str] = field(default_factory=list)
    #: 拟合结果对比图（generate / mcmc 且数据集里有二元体系时才有）
    figure: Any = None
    #: 图里的坐标轴列表（与 figure 配套）
    axes: List[Any] = field(default_factory=list)


# ---------------------------------------------------------------- 工具
def list_datasets(directory: str) -> List[Path]:
    """列出数据集目录下的全部 .json（递归，与 ESPEI 的 recursive_glob 对齐）。

    官方示例把 ZPF / 活性 / 热化学数据放在多层子目录里，只扫顶层会得到 0 个文件。
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.json") if p.is_file())


def load_phase_models(path: str) -> Dict[str, Any]:
    """读取 phase_models JSON。

    ESPEI 只把它当路径传给 ``json.load``，这里提前读一次是为了
    "文件坏掉"能在点击按钮的瞬间就报错，而不是等 ESPEI 跑到一半。
    """
    import json

    file_path = Path(path)
    try:
        with file_path.open(encoding="utf-8") as fp:
            data = json.load(fp)
    except json.JSONDecodeError as exc:
        raise CalculationError(
            f"phase_models 不是合法 JSON：{file_path.name}",
            f"第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}",
        ) from exc
    except OSError as exc:
        raise CalculationError(f"无法读取 {file_path.name}", str(exc)) from exc
    if not isinstance(data, dict):
        raise CalculationError("phase_models 顶层必须是对象", f"实际读到 {type(data).__name__}")
    return data


def _coerce_tag_value(value: str) -> Any:
    """把 ``weight=0.1`` / ``weight=true`` 里的文本转成标量。"""
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def parse_tags(text: str) -> Dict[str, Dict[str, Any]]:
    """解析 ``system.tags``。

    三种写法都接受：

    * 空串：不启用（默认）
    * JSON 对象：``{"dft": {"excluded_model_contributions": ["idmix", "mag"]}}``
    * 简写：``dft:-idmix,-mag;estimated-entropy:-idmix,-mag,weight=0.1``
      （``-名字`` 追加到 ``excluded_model_contributions``，其余 ``键=值`` 覆盖）

    宏里没有空格分隔的余地，因此简写是官方 Cu-Mg 示例的首选写法。
    """
    import json

    text = (text or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CalculationError(
                "数据集标签不是合法 JSON",
                f"第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}",
            ) from exc
        if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
            raise CalculationError(
                "数据集标签必须是「标签名 → 设置」的对象",
                '例如 {"dft": {"excluded_model_contributions": ["idmix"]}}',
            )
        return data

    path = Path(text)
    if path.suffix.lower() in (".json", ".yaml", ".yml") and path.is_file():
        if path.suffix.lower() == ".json":
            return parse_tags(path.read_text(encoding="utf-8"))
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - ESPEI 依赖 PyYAML
            raise CalculationError("读取 YAML 标签需要 PyYAML", str(exc)) from exc
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise CalculationError(f"标签文件 {path.name} 顶层必须是对象", "实际不是")
        return data

    tags: Dict[str, Dict[str, Any]] = {}
    for chunk in text.replace("；", ";").replace(";", "\n").splitlines():
        chunk = chunk.strip()
        if not chunk:
            continue
        tag, sep, spec = chunk.partition(":")
        tag = tag.strip()
        if not sep or not tag:
            raise CalculationError(
                f"数据集标签 {chunk!r} 格式不正确",
                "写成「标签名:-排除项,weight=数值」，例如 dft:-idmix,-mag",
            )
        updates = tags.setdefault(tag, {})
        excluded: List[str] = []
        for item in spec.split(","):
            item = item.strip()
            if not item:
                continue
            if item.startswith("-"):
                excluded.append(item[1:].strip())
            elif "=" in item:
                key, _, value = item.partition("=")
                updates[key.strip()] = _coerce_tag_value(value.strip())
            else:
                raise CalculationError(
                    f"数据集标签 {tag} 里的 {item!r} 无法识别",
                    "排除项写成 -idmix，其余设置写成 weight=0.1",
                )
        if excluded:
            updates["excluded_model_contributions"] = excluded
    return tags


def parse_aicc_penalty(text: str) -> Optional[Dict[str, Dict[str, float]]]:
    """解析 ``aicc_penalty_factor``。

    接受 JSON（``{"LIQUID": {"HM": 1.4}}``）或简写
    ``LIQUID:HM=1.4,LIQUID:SM=1.4``。空串返回 ``None``（ESPEI 默认不惩罚）。
    """
    import json

    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CalculationError(
                "AICc 惩罚不是合法 JSON",
                f"第 {exc.lineno} 行第 {exc.colno} 列：{exc.msg}",
            ) from exc
        if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
            raise CalculationError(
                "AICc 惩罚必须是「相名 → {数据类: 倍数}」的对象",
                '例如 {"LIQUID": {"HM": 1.4, "SM": 1.4}}',
            )
        return data

    result: Dict[str, Dict[str, float]] = {}
    for chunk in text.replace("；", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        phase, sep, spec = chunk.partition(":")
        key, eq, value = spec.partition("=")
        if not sep or not eq:
            raise CalculationError(
                f"AICc 惩罚 {chunk!r} 格式不正确",
                "写成「相名:数据类=倍数」，例如 LIQUID:HM=1.4",
            )
        try:
            factor = float(value)
        except ValueError as exc:
            raise CalculationError(
                f"AICc 惩罚 {chunk!r} 的倍数不是数字",
                "例如 LIQUID:HM=1.4",
            ) from exc
        result.setdefault(phase.strip().upper(), {})[key.strip().upper()] = factor
    return result


def check_datasets(directory: str, progress: ProgressCB = None) -> EspeiResult:
    """只校验数据集，不训练。返回每个数据集的校验结果（坏事不出库）。"""
    from espei.datasets import check_dataset, load_datasets
    from espei.utils import PickleableTinyDB

    files = list_datasets(directory)
    t0 = time.perf_counter()
    if not files:
        raise CalculationError(
            "数据集目录里没有找到任何 .json 数据集",
            "ESPEI 在数据目录中递归搜索 *.json，请确认选的是目录而不是单个文件",
        )
    if progress is not None:
        progress(0, max(1, len(files)), f"发现 {len(files)} 个数据集，正在逐个校验…")

    errors: List[str] = []
    for i, file_path in enumerate(files, start=1):
        try:
            load_datasets([str(file_path)])
        except Exception as exc:  # noqa: BLE001 - ESPEI 抛的异常类型不固定
            errors.append(f"{file_path.name}: {type(exc).__name__}: {exc}")
        if progress is not None:
            progress(i, len(files), f"已校验 {i}/{len(files)} 个数据集")
    if errors:
        raise CalculationError(
            f"{len(errors)} 个数据集不合法",
            "；".join(errors[:3]) + ("…" if len(errors) > 3 else ""),
        )
    return EspeiResult(
        mode="check",
        elapsed_s=time.perf_counter() - t0,
        n_datasets=len(files),
    )


def _build_run_settings(settings: EspeiSettings) -> Dict[str, Any]:
    """把 UI 配置翻译成 ESPEI 的 run_settings。

    这里刻意**不**自己拼 schema，而是让 ESPEI 的 ``get_run_settings`` 做归一化与校验——
    上游 schema 变了，界面不用跟着改；界面上填错的提示也和命令行一致。
    """
    from espei.validation import schema
    from espei.espei_script import get_run_settings

    weights = dict(settings.data_weights) or {}
    for key in ESPEI_DATA_WEIGHTS:
        # ESPEI 的默认值是 {'ZPF':1.0,'ACR':1.0,'HM':1.0,'SM':1.0,'CPM':1.0}
        weights.setdefault(key, 1.0)

    run_settings: Dict[str, Any] = {
        "system": {
            "phase_models": settings.phase_models,
            "datasets": settings.datasets,
        },
        "output": {
            "verbosity": int(settings.verbosity),
            "output_db": settings.output_db,
            "tracefile": "None",
            "probfile": "None",
        },
    }
    if settings.tags:
        run_settings["system"]["tags"] = copy.deepcopy(settings.tags)

    if settings.mode == "mcmc":
        scheduler = (settings.scheduler or "none").strip().lower()
        prior: Dict[str, Any] = {"name": settings.prior}
        if settings.prior != "zero":
            if settings.prior_loc_relative is not None:
                prior["loc_relative"] = float(settings.prior_loc_relative)
            if settings.prior_scale_relative is not None:
                prior["scale_relative"] = float(settings.prior_scale_relative)
        run_settings["mcmc"] = {
            "iterations": int(settings.iterations),
            "save_interval": max(1, int(settings.save_interval)),
            "scheduler": None if scheduler in ("none", "null", "serial") else settings.scheduler,
            "cores": max(1, int(settings.cores)),
            "input_db": settings.input_db,
            "prior": prior,
            "deterministic": True,
            "data_weights": weights,
            "chains_per_parameter": int(settings.chains_per_parameter),
            "chain_std_deviation": float(settings.chain_std_deviation),
        }
    else:
        run_settings["generate_parameters"] = {
            "excess_model": settings.excess_model,
            "ref_state": settings.ref_state,
            "ridge_alpha": settings.ridge_alpha,
            "aicc_penalty_factor": copy.deepcopy(settings.aicc_penalty_factor),
            # schema 里虽然写了 default，但 cerberus 的归一化不会补齐这条；
            # 不显式带上会报 "fitting_description must be of string type"
            "fitting_description": DEFAULT_FITTING_DESCRIPTION,
        }
        if settings.input_db:
            run_settings["generate_parameters"]["input_db"] = settings.input_db

    # 归一化 + 校验；抛出的异常属于 ESPEI schema 层，翻译成中文。
    #
    # ⚠ 必须传副本：cerberus 的 ``normalized()`` 会**原地修改**传入的 dict，
    # 把 ``fitting_description`` 从字符串换成 import 进来的对象。若把这次调用
    # 的返回值直接交回给 ``espei_script.run_espei``，它会再归一化一次，
    # 于是同一个对象被判定为 "must be of string type"（工程师踩过，见 ARCHITECTURE T48）。
    try:
        get_run_settings(copy.deepcopy(run_settings))
    except Exception as exc:  # noqa: BLE001
        log_exception(exc, "校验 ESPEI 运行参数")
        raise _settings_error(exc) from exc
    return run_settings


#: (关键词, 人话解释) —— 专门针对 ESPEI input-schema 的高频报错
_SCHEMA_HINTS: tuple = (
    ("fitting_description", "generate_parameters 需要显式给出 fitting_description"),
    ("excess_model", "多余自由能模型目前只支持 linear"),
    ("ref_state", "参考态只支持 SGTE91 / SR2016"),
    ("chains_per_parameter", "chains_per_parameter 必须是 ≥2 的偶数"),
    ("restart_trace", "restart_trace 需要配合 mcmc.input_db 一起填"),
    ("iterations", "MCMC 的 iterations 必须是 ≥0 的整数"),
    ("datasets", "system.datasets 必须指向存放 .json 数据集的目录"),
    ("phase_models", "system.phase_models 必须指向一个 .json 相模型文件"),
    ("output_db", "output.output_db 是 ESPEI 写出 TDB 的路径"),
)


def _settings_error(exc: BaseException) -> CalculationError:
    """把 cerberus / schema 的报错翻成人话。

    ESPEI 把 cerberus 的错误塞在一个 JSON 字符串里
    （形如 ``{'generate_parameters': [{'ridge_alpha': ['must be of float type']}]}``），
    直接展示给用户完全看不懂，所以按顶层键逐个给解释。
    """
    text = f"{type(exc).__name__}: {exc}"
    detail_parts: List[str] = []
    for key, hint in _SCHEMA_HINTS:
        if f"'{key}'" in text or f'"{key}"' in text:
            detail_parts.append(hint)
    if not detail_parts:
        for line in str(exc).splitlines():
            line = line.strip()
            if line and line not in detail_parts:
                detail_parts.append(line[:120])
    return CalculationError(
        "ESPEI 运行参数不合法，请检查面板填写",
        "；".join(detail_parts[:3]) or text[:300],
    )


# ---------------------------------------------------------------- 拟合对比图
def _plot_fit(database: Any, settings: "EspeiSettings", log=None):
    """用拟合后的数据库画「计算 vs 实验数据」对比图。

    eqplot 走 pycalphad 的 equilibrium，只支持二元 T-x 截面；数据集按
    体系（组分集合）分组，每个二元体系一个子图，最多画 4 个。三元或
    多元体系的数据点没有现成画法，跳过（交给相图计算页手工出）。
    本函数在工作线程里跑：Figure 直接构造，不碰 pyplot。
    """
    import numpy as np
    from matplotlib.figure import Figure

    from espei.datasets import load_datasets

    files = list_datasets(settings.datasets)
    if not files:
        return None, []
    datasets = load_datasets([str(f) for f in files])

    # 按体系分组：组分集合相同的数据集画进同一张子图
    groups: Dict[tuple, List[dict]] = {}
    for ds in datasets.all():
        comps = tuple(sorted(str(c) for c in ds.get("components", []) if c != "VA"))
        if comps:
            groups.setdefault(comps, []).append(ds)
    binaries = [(comps, dss) for comps, dss in groups.items() if len(comps) == 2]
    if not binaries:
        return None, []
    binaries = binaries[:4]  # 数据集很杂时别把图画成一排蚂蚁

    n = len(binaries)
    fig = Figure(figsize=(5.2 * n, 4.2), dpi=110)
    axes = list(fig.subplots(1, n, squeeze=False)[0])

    dbf_phases = sorted(database.phases.keys())
    for ax, (comps, dss) in zip(axes, binaries):
        try:
            # 数据集里出现过的温度范围决定计算的 T 网格
            tvals: List[float] = []
            for d in dss:
                t = d.get("conditions", {}).get("T")
                if t is None:
                    continue
                tvals.extend(t if isinstance(t, (list, tuple)) else [t])
            if not tvals:
                raise ValueError("数据集没有可用的温度条件")
            tmin, tmax = float(min(tvals)), float(max(tvals))
            if tmax - tmin < 1.0:  # 单点/窄区间数据：前后各放宽 50 K 才有线可画
                tmin, tmax = tmin - 50.0, tmax + 50.0

            from pycalphad import equilibrium, variables as v

            conds = {
                v.P: 101325,
                v.T: np.linspace(max(tmin, 1.0), tmax, 80),
                v.X(comps[1]): np.linspace(0.0, 1.0, 80),
            }
            eq = equilibrium(database, list(comps), dbf_phases, conds)

            from espei.plot import dataplot, eqplot

            # 不传 x / y，让 eqplot 按 equilibrium 的自由度自动选轴
            eqplot(eq, ax=ax)
            # dataplot 靠 conds 里的扫描维度判断画图类型：必须同时给出
            # 一个组分轴和一个势轴（T 或 P），否则会抛「projection ... cannot
            # be autodetected」。键必须是 pycalphad 的 StateVariable，传字符
            # 串会在内部 float() 转换时炸掉。
            dataplot(list(comps), dbf_phases,
                     {v.X(comps[1]): [0.0, 1.0], v.T: [tmin, tmax], v.P: 101325},
                     datasets, ax=ax)
            ax.set_title(" + ".join(comps), fontsize=11)
        except Exception as exc:  # noqa: BLE001 - 单个体系失败别拖垮整张图
            log_exception(exc, f"ESPEI 对比图 {comps}")
            if log is not None:
                log(f"# 跳过 {' + '.join(comps)} 的对比图：{exc}")
            ax.set_visible(False)
    return fig, axes


# ---------------------------------------------------------------- 主入口
def run_espei(
    settings: EspeiSettings,
    progress: ProgressCB = None,
    should_cancel=None,
    log: Optional[Callable[[str], None]] = None,
) -> EspeiResult:
    """执行一次 ESPEI 任务。

    Parameters
    ----------
    settings
        界面收集的配置，调用前应已 :meth:`EspeiSettings.validate`。
    progress
        可选进度回调（``(已完成, 总数, 提示)``）。
    should_cancel
        取消令牌查询闭包；ESPEI 内部没有检查点，取消只在**任务开始前**生效。
    log
        可选文本回调，接收 ESPEI 的日志行。ESPEI 自己把日志写进 root logger，
        不接这条通道的话界面上除了一开始的提示什么也看不到。

    Raises
    ------
    CalculationError
        参数不合法、数据集有问题或 ESPEI 运行失败。
    """
    import os

    settings.validate()
    t0 = time.perf_counter()

    if should_cancel is not None and should_cancel():
        from ..workers.base_worker import _Cancelled

        raise _Cancelled()

    if settings.mode == "check":
        result = check_datasets(settings.datasets, progress=progress)
        result.elapsed_s = time.perf_counter() - t0
        return result

    # 下面会 chdir 到输出目录（ESPEI 的 log/trace 都按相对路径落盘），
    # 相对路径必须先钉成绝对路径，否则 phase_models / datasets 会在错误目录里找。
    settings = copy.copy(settings)
    here = Path.cwd()

    def _absolute(value: str) -> str:
        if not value:
            return ""
        path = Path(value)
        return str(path if path.is_absolute() else (here / path).resolve())

    settings.phase_models = _absolute(settings.phase_models)
    settings.datasets = _absolute(settings.datasets)
    settings.input_db = _absolute(settings.input_db)
    settings.output_db = _absolute(settings.output_db)
    settings.output_dir = _absolute(settings.output_dir)

    if settings.output_dir:
        output_root = Path(settings.output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        # ESPEI 的 log / trace 都写到当前工作目录，切过去再切回来
        previous_cwd = Path.cwd()
        os.chdir(output_root)
    else:
        previous_cwd = None

    #: ESPEI 的日志走 root logger，这里把它接进 UI 的文本通道
    capture = _LogCapture(sink=log if log is not None else (lambda text: None))
    global _ACTIVE_CAPTURE, _ORIGINAL_CONFIG_LOGGER
    try:
        import espei
        import espei.logger

        _ORIGINAL_CONFIG_LOGGER = espei.logger.config_logger
        _ACTIVE_CAPTURE = capture
        # espei_script.run_espei 通过属性访问调用它，替换能被看见
        espei.logger.config_logger = _config_logger_with_capture
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(capture)

        run_settings = _build_run_settings(settings)
        if progress is not None:
            progress(0, 100, "正在载入数据集并训练…")

        from espei.espei_script import run_espei as _run

        # 返回值形态随模式变化：generate 只回一个 Database，mcmc 回 (Database, sampler)
        output = _run(run_settings)
        if isinstance(output, tuple):
            database = output[0]
        else:
            database = output
        output_path = Path(settings.output_db).resolve()
        if not output_path.is_file():
            raise CalculationError(
                f"ESPEI 没有产出预期的数据库：{output_path.name}",
                f"请检查输出路径是否被占用：{output_path}",
            )
        figure, axes = None, []
        if settings.mode in ("generate", "mcmc"):
            # 拟合完了就顺手画一张「计算 vs 实验数据」，仍在工作线程里，
            # equilibrium 的耗时不会卡界面；失败只记日志，别让图毁了拟合结果
            try:
                if progress is not None:
                    progress(0, 100, "正在绘制拟合对比图…")
                figure, axes = _plot_fit(database, settings, log=log)
            except Exception as exc:  # noqa: BLE001 - 画图失败不影响交付
                log_exception(exc, "ESPEI 拟合对比图")
                if log is not None:
                    log(f"# 对比图生成失败（不影响拟合产物）：{exc}")
        return EspeiResult(
            mode=settings.mode,
            elapsed_s=time.perf_counter() - t0,
            database=database,
            output_db=output_path,
            n_datasets=len(list_datasets(settings.datasets)),
            log_lines=list(capture.lines),
            figure=figure,
            axes=axes,
        )
    except CalculationError:
        raise
    except Exception as exc:  # noqa: BLE001 - 引擎边界统一翻译
        log_exception(exc, f"ESPEI {settings.mode}")
        raise _espei_failure(exc, settings) from exc
    finally:
        _ACTIVE_CAPTURE = None
        if _ORIGINAL_CONFIG_LOGGER is not None:
            import espei.logger

            espei.logger.config_logger = _ORIGINAL_CONFIG_LOGGER
        root = logging.getLogger()
        for handler in [h for h in root.handlers if h is capture]:
            root.removeHandler(handler)
        if previous_cwd is not None:
            os.chdir(previous_cwd)


def _espei_failure(exc: BaseException, settings: EspeiSettings) -> CalculationError:
    """ESPEI 运行期异常的中文诊断。"""
    text = f"{type(exc).__name__}: {exc}"
    needles = (
        (
            "No datasets were found in the path",
            "数据集目录里没有找到任何 .json 数据集",
            "ESPEI 在数据目录中递归搜索 *.json，请确认选的是目录而不是单个文件",
        ),
        (
            "Cannot determine type of dataset",
            "数据集无法识别类型",
            "数据集需要填写 output 键（ZPF / ACR / HM / SM / CPM）",
        ),
        (
            "chains_per_parameter",
            "MCMC 的 chains_per_parameter 必须是偶数且不小于 2",
            "它与每条链的参数个数有关：偶数 walks 才跑得动 emcee",
        ),
        (
            "restoring best fit",
            "MCMC 没有恢复出最优参数",
            "迭代次数太少或先验设置不当，可增大迭代次数",
        ),
        (
            "No calculations converged",
            "MCMC 迭代过程中没有任何一步收敛",
            "起始数据库可能缺少待拟合的相模型",
        ),
        (
            "No module named",
            "缺少依赖",
            "ESPEI 需要 dask / distributed / emcee / cerberus，可执行 pip install -e .[espei]",
        ),
    )
    for needle, reason, suggestion in needles:
        if needle in text:
            return CalculationError(f"ESPEI {settings.mode} 失败：{reason}", f"{suggestion}。原始信息：{text[:200]}")
    translated = diagnose(exc, f"ESPEI {settings.mode}")
    return translated


# ---------------------------------------------------------------- 工具
def save_database(database: Any, path: str) -> Path:
    """把 ESPEI 产出的 Database 写成 TDB 文件。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        database.to_file(str(target), if_exists="overwrite")
    except Exception as exc:  # noqa: BLE001
        log_exception(exc, f"写出数据库 {target.name}")
        raise CalculationError(
            f"写出数据库失败：{target.name}",
            f"请确认目录可写。原始信息：{type(exc).__name__}: {exc}",
        ) from exc
    return target

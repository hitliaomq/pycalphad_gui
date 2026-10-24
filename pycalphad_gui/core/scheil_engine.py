"""Scheil / 平衡凝固模拟引擎（纯 Python，不依赖 PyQt6）。

封装 `scheil 0.3.0 <https://github.com/PhasesResearchLab/scheil>`_ 的两个入口：

* :func:`~scheil.simulate.simulate_scheil_solidification` —— Scheil–Gulliver 非平衡凝固
* :func:`~scheil.simulate.simulate_equilibrium_solidification` —— 平衡凝固

与旧版（0.1/0.2）不同，0.3.0 的 Python API **不是** ``ScheilSimulator``，
而是两个自由函数 + ``SolidificationResult``，见 :func:`run_solidification`。

踩过的上游坑（都在这里兜住，不往 UI 层漏）：

1. ``liquid_phase_name`` 必须是库里真实存在的相名。传默认的 ``'LIQUID'`` 而库里
   液相叫 ``IONIC_LIQ`` 时，scheil 会一路"没找到液相 → 缩小步长"直到步数用尽，
   然后在收尾处抛 :class:`UnboundLocalError`（见 :func:`_friendly_failure`）。
2. ``eq_kwargs`` 缺省为 ``None`` 时若 ``adaptive=False``，scheil 会
   ``KeyError: 'calc_opts'``。默认始终走 ``adaptive=True``。
3. ``solidification.to_dataframe()`` 只有**瞬时**相分数与相成分，没有累计相分数；
   界面要画"固相分数–温度"曲线得自己用 ``fraction_solid`` / ``cum_phase_amounts`` 拼表。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from .database_manager import LoadedDatabase
from .diagnostics import CalculationError, diagnose, log_exception
from ..config import LIQUID_NAME_HINTS, SCHEIL_METHODS

#: 进度回调类型：callable(已完成, 总数, 提示文本)
ProgressCB = Optional[Any]


@dataclass
class ScheilConfig:
    """一次凝固模拟的全部输入。

    composition 用**元素符号（库内原样，如 ``'ZR'``）→ 摩尔分数**描述，
    由 :meth:`ScheilConfig.build` 翻成 scheil 需要的 ``{v.X('V'): 0.7}`` 形式。
    """

    database: LoadedDatabase
    #: 计算组分（含 VA）
    comps: Sequence[str]
    #: 参与计算的相
    phases: Sequence[str]
    #: 元素 → 摩尔分数，之和不必为 1（不足部分由 VA 补齐）
    composition: Dict[str, float]
    #: 起始温度，必须落在单一液相区内
    start_temperature: float = 2000.0
    #: 温度步长
    step_temperature: float = 5.0
    #: 被当作"液相"的相名；为空时由 :func:`guess_liquid_phase` 推断
    liquid_phase_name: str = ""
    #: 液相分数低于此值时停止
    stop: float = 0.0001
    #: 自适应采样（scheil 0.3.0 下关掉会 ``KeyError: 'calc_opts'``，默认保持开启）
    adaptive: bool = True
    #: ``'scheil'`` 或 ``'equilibrium'``
    method: str = "scheil"

    def build(self) -> tuple:
        """组装成 ``(传给 scheil 的关键字参数, 展示用元数据)``。

        两者必须分开：scheil 不接受 ``**kwargs``，元数据显示进去会直接
        ``TypeError: unexpected keyword argument``。
        """
        if self.method not in SCHEIL_METHODS:
            raise CalculationError(
                f"不支持的凝固方法：{self.method}",
                f"可选：{', '.join(SCHEIL_METHODS)}",
            )
        if len(self.composition) < 1:
            raise CalculationError("请至少设置一个元素成分", "否则体系没有确定的成分点")
        total = float(sum(float(v) for v in self.composition.values()))
        if total <= 0:
            raise CalculationError("成分总和必须大于 0", "请检查摩尔分数是否填反了")

        import pycalphad.variables as v

        # scheil 的 composition 只收**独立**组分：对于 n 元体系只能给 n-1 个摩尔分数，
        # 剩下的那个由 balance 隐含。给全了（比如二元给 {V:0.7, ZR:0.3}）会直接触发
        # pycalphad 的 "Number of degrees of freedom is not zero"。
        # 这里统一丢掉最后一个元素（当作溶剂），并在 summary 里回报它。
        real: List[str] = []
        for name, value in self.composition.items():
            resolved = self.database.resolve(name) or name
            if resolved in real:
                continue
            if float(value) <= 0:
                continue
            real.append(resolved)
        if not real:
            raise CalculationError(
                "请填写至少一个元素的摩尔分数",
                "成分点为空时 scheil 无法构造条件",
            )
        solvent = real.pop() if len(real) > 1 else None
        total_kept = sum(float(self.composition[k]) for k in real)
        if total_kept >= 1.0:
            raise CalculationError(
                "已填组分的摩尔分数之和必须小于 1",
                f"当前已填 {total_kept:.4f}，剩余量（溶剂 {solvent or 'VA'}）不能为负",
            )
        composition = {v.X(name): float(self.composition[name]) for name in real}
        comps = list(self.comps)
        if "VA" not in comps and "VA" in self.database.all_elements:
            comps.append("VA")
        phases = [p for p in self.phases if p]
        if not phases:
            raise CalculationError("没有选中任何相", "请至少启用一个相")

        liquid = self.liquid_phase_name or guess_liquid_phase(self.database, phases)
        if liquid and liquid not in phases:
            raise CalculationError(
                f"液相候选 {liquid!r} 不在启用的相列表里",
                f"当前启用的相：{', '.join(phases)}",
            )

        return {
            "comps": comps,
            "phases": phases,
            "composition": composition,
            "start_temperature": float(self.start_temperature),
            "step_temperature": max(1e-6, float(self.step_temperature)),
            "liquid_phase_name": liquid,
            "stop": float(self.stop),
            "adaptive": bool(self.adaptive),
            "output": None,
        }, {
            # 展示用：这几个条件按"独立组分"理解，solvent 是剩下的那个
            "independent": list(composition.keys()),
            "solvent": solvent,
        }


@dataclass
class ScheilResult:
    """一次凝固模拟的产物：一张图 + 一张表 + 一段文字摘要。"""

    figure: Figure
    axes: Axes
    #: 温度 (K) / 固相分数 / 液相分数 / 各相累计分数
    frame: Any
    #: 关键的模拟结论
    summary: Dict[str, Any] = field(default_factory=dict)
    method: str = "scheil"
    elapsed_s: float = 0.0
    #: 液相是否成功耗尽（False 往往意味着模拟没跑到底）
    converged: bool = False
    title: str = ""

    def axes_list(self) -> List[Axes]:
        return [self.axes]


# ---------------------------------------------------------------- 工具
def guess_liquid_phase(database: LoadedDatabase, phases: Sequence[str] = ()) -> str:
    """从相名里猜液相。

    很多 TDB 不叫 ``LIQUID``（例如 ``IONIC_LIQ``、``Liquid``），猜错了 scheil 会在
    "找不到液相 → 缩小步长"的死循环里把步数耗光，最后在收尾处抛出
    ``UnboundLocalError: current_fraction_solid``（scheil 0.3.0 的已知缺陷）。
    所以这里按 :data:`LIQUID_NAME_HINTS` 的顺序匹配一次，能省掉一大类报错。
    """
    candidates = list(phases) or list(database.phase_names)
    for hint in LIQUID_NAME_HINTS:
        for name in candidates:
            if name.upper() == hint.upper():
                return name
    for name in candidates:
        if "LIQUID" in name.upper():
            return name
    return "LIQUID"


def _result_frame(temperatures, fraction_solid, fraction_liquid, cum_phase_amounts) -> Any:
    """把 SolidificationResult 的关键量拼成 DataFrame。

    必须用 numpy 数组而不是 list：每行长度可能不一致（瞬时相分数会按"看到的相"补齐），
    直接 ``pd.DataFrame(list_of_dicts)`` 会得到 object dtype 的列，后面画图会 TypeError。
    """
    import pandas as pd

    cols: Dict[str, np.ndarray] = {
        "温度 (K)": np.asarray(temperatures, dtype=float),
        "固相分数": np.asarray(fraction_solid, dtype=float),
        "液相分数": np.asarray(fraction_liquid, dtype=float),
    }
    for phase_name, values in cum_phase_amounts.items():
        arr = np.asarray(values, dtype=float)
        width = max(len(cols["温度 (K)"]), arr.size)
        padded = np.zeros(width, dtype=float)
        padded[: arr.size] = arr
        cols[f"{phase_name} 分数"] = padded
    return pd.DataFrame(cols)


def _plot(result: Any, axes: Axes, title: str) -> None:
    """画固相分数–温度曲线与各相的析出曲线。

    注意：温度轴**反向**（从左到右 3000 K → 1000 K），这是凝固图的通行画法。
    反向要放在 :func:`run_solidification` 末尾统一落定，不在本函数里碰范围。
    """
    temps = np.asarray(result.temperatures, dtype=float)
    axes.plot(
        temps,
        np.asarray(result.fraction_solid, dtype=float),
        color="#1f77b4",
        lw=1.8,
        label="固相总量",
    )
    for phase_name, values in (result.cum_phase_amounts or {}).items():
        arr = np.asarray(values, dtype=float)
        axes.plot(temps, arr, lw=1.2, alpha=0.85, label=str(phase_name))
    axes.set_xlabel("温度 T (K)")
    axes.set_ylabel("分数")
    axes.set_title(title)
    axes.legend(loc="best", fontsize=8)
    axes.grid(True, alpha=0.3)


# ---------------------------------------------------------------- 主入口
def run_solidification(
    config: ScheilConfig,
    figure: Optional[Figure] = None,
    progress: ProgressCB = None,
    should_cancel=None,
) -> ScheilResult:
    """执行一次凝固模拟并出图。

    Parameters
    ----------
    config
        模拟输入，见 :class:`ScheilConfig`。
    figure
        复用的画布；为 None 时新建（**必须**在后台线程里用 Agg 后端创建）。
    progress
        可选进度回调。
    should_cancel
        取消令牌查询闭包。

    Raises
    ------
    CalculationError
        条件不合法或模拟失败。scheil 自身的三类上游崩溃在这里被翻译成人话。
    """
    from scheil.simulate import (
        simulate_equilibrium_solidification,
        simulate_scheil_solidification,
    )

    t0 = time.perf_counter()
    kwargs, meta = config.build()

    if should_cancel is not None and should_cancel():
        from ..workers.base_worker import _Cancelled

        raise _Cancelled()

    if progress is not None:
        _report(progress, 1, 4, "正在准备相模型与初始态…")

    func = (
        simulate_equilibrium_solidification
        if config.method == "equilibrium"
        else simulate_scheil_solidification
    )
    # 两个入口的参数表并不相同：平衡凝固没有 stop（它靠二分搜索逼近固相线），
    # 多传一个就是 ``TypeError: unexpected keyword argument 'stop'``。
    if config.method == "equilibrium":
        kwargs.pop("stop", None)
    # adaptive 默认 True：scheil 在 adaptive=False 且 eq_kwargs 为 None 时会 KeyError
    try:
        solidification = func(  # type: ignore[operator]
            config.database.dbf, **kwargs
        )
    except CalculationError:
        raise
    except UnboundLocalError as exc:
        # 典型的 "liquid_phase_name 猜错" signal：scheil 步数耗光后收尾引用了未定义变量
        log_exception(exc, f"{config.method} 凝固模拟收尾")
        raise CalculationError(
            "凝固模拟没有跑到底：在到达终点前就用尽了温度步长",
            f"请把「液相相名」改成本库真实的液相（如 {guess_liquid_phase(config.database, kwargs['phases'])}），"
            f"或把起始温度提高、加大温度步长。原始信息：{exc}",
        ) from exc
    except ZeroDivisionError as exc:
        log_exception(exc, f"{config.method} 凝固模拟求解")
        raise CalculationError(
            "凝固模拟在求解某一步时数值发散",
            "常见于起始温度太低（不是单一液相区）或温度步长过大，"
            f"建议把起始温度提到 {config.start_temperature + 300:.0f} K 左右再试。原始信息：{exc}",
        ) from exc
    except Exception as exc:  # noqa: BLE001 - 引擎边界统一翻译
        log_exception(exc, f"{config.method} 凝固模拟")
        raise _friendly_failure(exc, config) from exc

    if progress is not None:
        _report(progress, 3, 4, "正在汇总结果…")

    frame = _result_frame(
        solidification.temperatures,
        solidification.fraction_solid,
        getattr(solidification, "fraction_liquid", None)
        or (1.0 - np.asarray(solidification.fraction_solid, dtype=float)),
        getattr(solidification, "cum_phase_amounts", {}) or {},
    )

    if figure is None:
        figure = Figure(figsize=(7.0, 5.0))
    axes = figure.subplots()
    title = (
        f"{'平衡' if config.method == 'equilibrium' else 'Scheil'}凝固 — "
        f"{config.database.name}"
    )
    _plot(solidification, axes, title)

    fraction_liquid = np.asarray(
        getattr(solidification, "fraction_liquid", None) or
        (1.0 - np.asarray(solidification.fraction_solid, dtype=float)),
        dtype=float,
    )
    independent = meta.get("independent") or []
    solvent = meta.get("solvent")
    summary = {
        "方法": "平衡凝固" if config.method == "equilibrium" else "Scheil–Gulliver",
        "成分点": (
            "，".join(f"X({str(c)[2:]}) = {float(v):.4f}" for c, v in
                      zip(independent, config.composition.values()))
            + (f"，其余为 {solvent}" if solvent else "")
        ),
        "起点温度 (K)": round(float(solidification.temperatures[0]), 2),
        "终点温度 (K)": round(float(solidification.temperatures[-1]), 2),
        "步数": len(solidification.temperatures),
        "最终固相分数": round(float(solidification.fraction_solid[-1]), 4),
        "剩余液相": (
            f"{float(fraction_liquid[-1]):.4f}" if fraction_liquid.size else "—"
        ),
        "析出相": ", ".join(
            sorted((solidification.cum_phase_amounts or {}).keys())
        )
        or "—",
        # scheil 的 converged 只在"液相低于 stop"那一刻置 True；若靠步数用尽退出，
        # 但固相分数已经到 1，实际也算跑完了，别让用户误以为失败。
        "是否收敛": (
            "是"
            if (bool(solidification.converged)
                or float(solidification.fraction_solid[-1]) >= 1.0)
            else "否（未走完，可加大温度步长）"
        ),
    }

    if progress is not None:
        _report(progress, 4, 4, "完成")

    # ---- 范围落定（顺序有讲究，别调换）-------------------------------
    # 1) autoscale_view()：与 T46 同理，引擎交付前必须把范围算实，
    #    否则画布挂载时 set_autoscale_on(False) 会让挂起的请求作废，viewLim 停在默认 (0,1)。
    axes.autoscale_view()
    # 2) 反向温度轴：凝固图从左到右降温。必须在 autoscale 之后显式写死，
    #    再关掉 autoscale，否则 set_figure 快照到的初始范围会变成升序。
    temps = np.asarray(solidification.temperatures, dtype=float)
    if temps.size:
        axes.set_xlim(float(temps.max()), float(temps.min()))
    axes.set_autoscale_on(False)

    return ScheilResult(
        figure=figure,
        axes=axes,
        frame=frame,
        summary=summary,
        method=config.method,
        elapsed_s=time.perf_counter() - t0,
        converged=bool(solidification.converged),
        title=title,
    )


def _friendly_failure(exc: BaseException, config: ScheilConfig) -> CalculationError:
    """把 scheil 抛出的异常翻成中文诊断。"""
    text = f"{type(exc).__name__}: {exc}"
    needles = (
        (
            "No calculations converged",
            "没有任何一步求解收敛",
            "请检查起始温度是否落在单一液相区、所选元素能否让液相激活",
        ),
        (
            "Cannot determine type of dataset",
            "数据集类型无法识别",
            "这与凝固模拟无关，可能是相名写错导致相模型无法匹配",
        ),
        (
            "has no attribute",
            "相模型与组分不匹配",
            "请检查是否启用了不含所选元素的相",
        ),
        (
            "ActivePhaseError",
            "所选组分下没有任何相处于活跃状态",
            "请换一组元素或放宽相的启用范围",
        ),
    )
    for needle, reason, suggestion in needles:
        if needle in text:
            return CalculationError(
                f"凝固模拟失败：{reason}",
                f"{suggestion}。原始信息：{text[:200]}",
            )
    return diagnose(exc, f"{config.method} 凝固模拟")


# ---------------------------------------------------------------- 工具
def _report(progress: ProgressCB, cur: int, total: int, msg: str) -> None:
    """安全调用进度回调。"""
    if progress is None:
        return
    try:
        progress(cur, total, msg)
    except Exception:  # pragma: no cover
        pass

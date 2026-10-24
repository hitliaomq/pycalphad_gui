"""高通量批量计算。

对条件空间做笛卡尔展开，逐点求解平衡态并抽取指标，最终汇成一张表格。

并行策略（见 ARCHITECTURE 4.4）：
* 默认线程池——``Database`` 可安全共享，取消机制简单；
* 可选进程池——``Database`` 实测可 pickle（26 KB / <10 ms），适合 CPU 密集场景。
"""
from __future__ import annotations

import itertools
import math
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pycalphad.variables as v
from pycalphad import equilibrium

from .database_manager import LoadedDatabase
from .diagnostics import CalculationError, diagnose, log_exception

ProgressCB = Optional[Callable[[int, int, str], None]]
CancelCB = Optional[Callable[[], bool]]

#: 每个输出指标的名称 → 中文列头
OUTPUT_LABELS: Dict[str, str] = {
    "stable_phases": "稳定相组合",
    "gm_min": "最低G (J/mol)",
    "gm_last": "末态G (J/mol)",
    "np_liquid": "液相分数",
    "n_phases": "共存相数",
}


@dataclass
class HTConfig:
    """高通量任务配置。"""

    database: LoadedDatabase
    comps: Sequence[str]
    phases: Sequence[str]
    #: {目标: 采样序列}，如 {"T": [1000, 1100], "AL": [0.3, 0.5]}
    sweeps: Dict[str, Sequence[float]]
    outputs: Sequence[str] = ("stable_phases", "gm_min", "n_phases")
    parallel: int = 4
    use_process_pool: bool = False
    #: 传给 equilibrium 的额外参数
    solver_kwargs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.sweeps:
            raise CalculationError("高通量任务至少需要指定一个扫描维度")
        for target in self.sweeps:
            if len(np.asarray(list(self.sweeps[target]), dtype=float)) == 0:
                raise CalculationError(f"扫描维度 {target} 没有采样点")

    @property
    def axis_order(self) -> List[str]:
        """扫描维度的固定顺序，保证多行结果表列顺序稳定。"""
        return list(self.sweeps.keys())

    @property
    def total_points(self) -> int:
        n = 1
        for target in self.axis_order:
            n *= len(np.asarray(list(self.sweeps[target]), dtype=float))
        return int(n)


@dataclass
class HTResult:
    """高通量结果。"""

    frame: pd.DataFrame
    elapsed_s: float
    n_total: int
    n_ok: int
    n_failed: int
    #: ``最低G`` 列取不到有限值的点数——区别于"失败"：点算出来了但无物理解
    n_degenerate: int = 0
    failures: List[Tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


def scalar_value(value: Any) -> Any:
    """把 numpy 标量还原成 Python 原生类型，非有限值统一转成 ``None``。

    背景：``len(...)`` 得到的 ``int`` 塞进 DataFrame 后，用 ``DataFrame.iat``
    读回来是 ``np.int64``；``np.int64`` **不是** Python ``int`` 的子类，下游
    一旦写 ``isinstance(x, (int, float, str))`` 就会把"共存相数"整列判成
    不可显示、清成空串（T49）。同理 ``np.float64`` 是 ``float`` 的子类而
    ``np.int64`` 不是，所以这个坑只埋在整数列上，特别隐蔽。

    NaN / ±inf 转成 ``None``：界面与 CSV 都会显示为空，而不是满屏 "nan"。
    """
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):  # bool 是 int 的子类，先拦住
        return bool(value)
    if isinstance(value, np.generic):  # np.int64 / np.float64 / np.str_ …
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


# ---------------------------------------------------------------- 单点点求解
def _target_to_statevar(database: LoadedDatabase, target: str):
    up = target.strip().upper()
    if up in ("T", "P", "N"):
        return {"T": v.T, "P": v.P, "N": v.N}[up]
    return v.X(database.resolve(target) or target)


def _liquid_fraction(eq: Any) -> float:
    """取 LIQUID 相的最大相分数，取不到时返回 0.0。

    ``eq.coords`` 里的 ``Phase`` 维度在部分数据库（如 V-Zr 的 IONIC_LIQ 体系）
    或无液相的解上会直接缺席，``eq.coords["Phase"]`` 会抛 ``KeyError``，
    把整点判成计算失败（T49）。同时坐标是 ``(vertices, phase)`` 二维的，
    必须 ravel 后按一维索引才能和 ``NP`` 对齐。
    """
    try:
        np_raw = np.asarray(eq["NP"].values, dtype=float).ravel()
    except (KeyError, IndexError, TypeError, ValueError):
        return 0.0
    if "Phase" not in eq.coords or np_raw.size == 0:
        return 0.0
    phase_coord = np.asarray(eq.coords["Phase"].values).ravel()
    idx = [i for i, p in enumerate(map(str, phase_coord)) if p.strip().upper() == "LIQUID"]
    if not idx:
        return 0.0
    return float(np_raw[idx].max())


def _extract(
    dbf: Any,
    comps: Sequence[str],
    phases: Sequence[str],
    conds: Dict,
    outputs: Sequence[str],
) -> Dict[str, Any]:
    """在单个条件下求解平衡态并抽取指标。"""
    eq = equilibrium(dbf, list(comps), list(phases), conds)
    phase_names = tuple(
        sorted({str(p) for p in np.asarray(eq["Phase"].values.ravel(), dtype="U") if str(p) != ""})
    )
    row: Dict[str, Any] = {"stable_phases": " + ".join(phase_names)}
    gm = np.asarray(eq["GM"].values, dtype=float).ravel()
    if gm.size:
        finite = gm[np.isfinite(gm)]
        if "gm_min" in outputs:
            row["gm_min"] = float(finite.min()) if finite.size else float("nan")
        if "gm_last" in outputs:
            row["gm_last"] = float(finite[-1]) if finite.size else float("nan")
    if "n_phases" in outputs:
        # 显式 int()：落成 Python 原生类型，别让下游拿 np.int64 去 isinstance
        row["n_phases"] = int(len(phase_names))
    if "np_liquid" in outputs:
        row["np_liquid"] = _liquid_fraction(eq)
    return row


def _worker(
    args: Tuple[
        Any, Tuple[str, ...], Tuple[str, ...], Dict[Any, float], Tuple[str, ...], Tuple[str, ...]
    ]
) -> Dict[str, Any]:
    """线程池 / 进程池的执行体。

    线程池下 ``database`` 是真实对象；进程池下 ``args[0]`` 是 pickle 还原的副本，
    因此这里不引用任何外部可变状态。

    返回记录的**键必须全部是字符串**：``conds`` 的键是 pycalphad 的 sympy
    ``Variable`` 对象，拿它当 DataFrame 列名时与轴名（``'T'`` / ``'V'``）匹配不上，
    会让整张结果表变成 NaN（T42）。
    """
    dbf, comps, phases, conds, outputs, axes = args
    row: Dict[str, Any] = {str(axis): float(val) for axis, val in zip(axes, conds.values())}
    row.update(_extract(dbf, comps, phases, conds, outputs))
    # 统一翻译成最终列名（轴名保持原样），保证与 DataFrame 的 columns 同名同序
    return {
        OUTPUT_LABELS.get(key, key): scalar_value(value) for key, value in row.items()
    }


def run_high_throughput(
    config: HTConfig,
    progress: ProgressCB = None,
    should_cancel: CancelCB = None,
) -> HTResult:
    """执行高通量扫描。

    Parameters
    ----------
    config
        任务配置。
    progress
        进度回调 ``(已完成, 总数, 提示)``。
    should_cancel
        取消判断回调；返回 True 时立即停止并只返回已完成任务。

    Returns
    -------
    HTResult
        结果表格与统计；失败点记录于 ``failures`` 而非静默丢弃。
    """
    t0 = time.perf_counter()
    axes = config.axis_order
    combos = list(itertools.product(*[np.asarray(list(config.sweeps[a]), dtype=float) for a in axes]))
    total = len(combos)

    records: List[Dict[str, Any]] = []
    failures: List[Tuple[str, str]] = []
    cancelled = False

    def _conds_of(values: Sequence[float]) -> Dict[str, float]:
        return {_target_to_statevar(config.database, a): float(x) for a, x in zip(axes, values)}

    # 参数化：线程池传 (dbf, comps, phases, conds, outputs, axes)
    def _payload(values: Sequence[float]):
        return (
            config.database.dbf,
            tuple(config.comps),
            tuple(config.phases),
            _conds_of(values),
            tuple(config.outputs),
            tuple(axes),
        )

    done = 0
    try:
        workers = max(1, int(config.parallel))
        if config.use_process_pool and workers > 1:
            executor: Any = ProcessPoolExecutor(max_workers=workers)
        else:
            executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="htcalc")

        with executor:
            futures = {executor.submit(_worker, _payload(values)): values for values in combos}
            for fut in as_completed(futures):
                if should_cancel is not None and should_cancel():
                    cancelled = True
                    for f in futures:
                        f.cancel()
                    break
                values = futures[fut]
                try:
                    records.append(fut.result())
                except Exception as exc:  # noqa: BLE001 - 单点失败不应终止整体
                    log_exception(exc, f"高通量点 {values}")
                    failures.append(
                        (
                            ", ".join(f"{a}={x:g}" for a, x in zip(axes, values)),
                            diagnose(exc, "高通量").user_message,
                        )
                    )
                done += 1
                if progress is not None:
                    msg = f"已完成 {done}/{total}"
                    try:
                        progress(done, total, msg)
                    except Exception:  # pragma: no cover
                        pass

    except CalculationError:
        raise
    except Exception as exc:  # noqa: BLE001
        log_exception(exc, "高通量计算")
        raise diagnose(exc, "高通量计算") from exc

    # records 的键已是"轴名 + 中文列头"，与 columns 严格同名同序。
    # 之前 records 用 sympy 变量键、columns 用字符串，两边对不上 → 整表 NaN。
    frame = pd.DataFrame(records, columns=axes + [OUTPUT_LABELS.get(o, o) for o in config.outputs])
    # as_completed 的返回顺序是"先算完先报"，按扫描轴排序后结果才可读、可比对
    if not frame.empty:
        sort_cols = [c for c in axes if c in frame.columns]
        if sort_cols:
            frame = (
                frame.sort_values(by=sort_cols, kind="stable").reset_index(drop=True)
            )

    # 区分"算抛异常"与"算出来了但无物理解"——只报失败数会掩盖后者
    n_degenerate = 0
    gm_col = OUTPUT_LABELS.get("gm_min", "gm_min")
    if not frame.empty and gm_col in frame.columns:
        col = pd.to_numeric(frame[gm_col], errors="coerce")
        n_degenerate = int(col.isna().sum())

    return HTResult(
        frame=frame,
        elapsed_s=time.perf_counter() - t0,
        n_total=total,
        n_ok=len(records),
        n_failed=len(failures),
        n_degenerate=n_degenerate,
        failures=failures,
        cancelled=cancelled,
    )

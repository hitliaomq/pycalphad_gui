"""条件构造与校验。

pycalphad 对各绘图函数的条件组合有**硬性**要求，违反时抛出的是英文异常，
用户很难自行修正。本模块把这些规则前置到构造阶段：

=========================  ==========================  ==================
相图类型                   组分扫描                     外部条件扫描
=========================  ==========================  ==================
二元 T–X（binplot）        恰好 1 个                    恰好 1 个（T 或 P）
三元等温截面（ternplot）   恰好 2 个                    0 个（必须等温）
二元平衡态（eqplot）       恰好 1 个                    恰好 1 个
三元平衡态（eqplot）       恰好 2 个                    0 个
=========================  ==========================  ==================

同时处理元素符号规范化（周期表的 ``Al`` → TDB 里的 ``AL``）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pycalphad.variables as v

from .database_manager import LoadedDatabase
from .diagnostics import CalculationError

#: 外部条件（势场）关键字
STATE_KEYS = ("T", "P", "N")

#: 每个相图类型要求的 (组分扫描数, 外部条件扫描数)
_SHAPE_RULES = {
    "binary_ztpf": (1, 1),
    "ternary_isothermal": (2, 0),
    "eqplot_binary": (1, 1),
    "eqplot_ternary": (2, 0),
    # 这两个在 validate 里走专属分支，元组仅占位
    "step": (1, 0),
    "isopleth": (1, 1),
}


def _fmt(values) -> str:
    arr = np.asarray(list(values), dtype=float)
    if arr.size == 0:
        return "空"
    if arr.size <= 4:
        return "[" + ", ".join(f"{x:g}" for x in arr) + "]"
    return f"[{arr[0]:g} … {arr[-1]:g}]（{arr.size} 点）"


@dataclass
class Sweep:
    """一个扫描维度。"""

    target: str          # 'T' / 'P' / 元素符号
    values: np.ndarray   # 采样点

    @property
    def is_state(self) -> bool:
        return self.target.upper() in STATE_KEYS

    @property
    def count(self) -> int:
        return int(np.asarray(self.values).size)

    def describe(self) -> str:
        kind = "外部条件" if self.is_state else "组分"
        return f"{kind} {self.target.upper()}: {_fmt(self.values)}"


@dataclass
class ConditionPlan:
    """一次计算的条件描述，是 UI 与引擎之间唯一的契约。"""

    sweeps: List[Sweep] = field(default_factory=list)
    fixed: Dict[str, float] = field(default_factory=dict)  # 未参与扫描的定值与固定外部条件
    diagram_type: str = "binary_ztpf"

    # ---------------------------------------------------------------- 构造
    @classmethod
    def from_ui(
        cls,
        database: LoadedDatabase,
        diagram_type: str,
        sweeps: Mapping[str, Sequence[float]],
        fixed: Optional[Mapping[str, float]] = None,
    ) -> "ConditionPlan":
        """由 UI 传入的 {目标: 采样序列} 构造计划。

        Parameters
        ----------
        database
            用于符号规范化。
        diagram_type
            见 :data:`_SHAPE_RULES` 的键。
        sweeps
            例如 ``{"T": (300, 1000, 10), "AL": (0, 1, 0.02)}``。
        fixed
            例如 ``{"P": 101325.0}``，未被扫描的势场默认值。

        Raises
        ------
        CalculationError
            条件组合不满足该相图类型的硬性要求。
        """
        if diagram_type not in _SHAPE_RULES:
            raise CalculationError(f"未知相图类型：{diagram_type}")

        sweep_objs: List[Sweep] = []
        for target, raw in sweeps.items():
            values = _as_samples(raw, target)
            if values.size == 0:
                raise CalculationError(
                    f"扫描维度 {target} 没有有效采样点",
                    "请检查起止值与步长",
                )
            sweep_objs.append(Sweep(target=target, values=values))

        plan = cls(sweeps=sweep_objs, fixed=dict(fixed or {}), diagram_type=diagram_type)
        plan.validate(database)
        return plan

    # ---------------------------------------------------------------- 校验
    def validate(self, database: Optional[LoadedDatabase] = None) -> None:
        """按相图类型校验维度数量，失败时给出中文修正建议。"""
        if self.diagram_type == "step":
            # 官方 StepStrategy：单轴步进，其余条件全部固定
            if len(self.sweeps) != 1:
                raise CalculationError(
                    "Step 图只需要 1 个扫描维度（温度、压强或成分）",
                    "请删除多余扫描维度只留一个；其余量在「固定条件」里固定",
                )
            self._validate_swept_components(database)
            return
        elif self.diagram_type == "isopleth":
            # 官方 IsoplethStrategy：1 个组分扫描 + 1 个温度扫描，
            # 多出来的自由度用固定成分钉住
            n_comp = sum(1 for s in self.sweeps if not s.is_state)
            n_state = sum(1 for s in self.sweeps if s.is_state)
            if n_comp != 1 or n_state != 1:
                raise CalculationError(
                    "Isopleth 垂直截面要求：组分扫描 1 个 + 温度扫描 1 个",
                    "再在「固定条件」里添加固定成分，钉住剩余自由度",
                )
            if not any(t.upper() not in STATE_KEYS for t in self.fixed):
                raise CalculationError(
                    "Isopleth 至少要固定 1 个成分（多出的自由度必须钉住）",
                    "请在「固定条件」里点「+ 添加固定成分」，填入元素与摩尔分数",
                )
            self._validate_swept_components(database)
            return
        need_comp, need_state = _SHAPE_RULES[self.diagram_type]
        n_comp = sum(1 for s in self.sweeps if not s.is_state)
        n_state = sum(1 for s in self.sweeps if s.is_state)

        if (n_comp, n_state) != (need_comp, need_state):
            msg = (
                f"「{' / '.join(_SHAPE_RULES)}」类相图要求："
                f"组分扫描 {need_comp} 个、外部条件扫描 {need_state} 个；"
                f"当前是组分 {n_comp} 个、外部条件 {n_state} 个。"
            )
            if need_comp == 1 and need_state == 1:
                fix = "请把温度或压力改为固定值，并只保留一个组分在扫描。"
            else:
                fix = "请把温度设为固定值，并让两个组分同时扫描。"
            raise CalculationError(msg, fix)

        self._validate_swept_components(database)

    def _validate_swept_components(self, database: Optional[LoadedDatabase]) -> None:
        """组分扫描目标必须能在库中找到，否则 pycalphad 会抛晦涩异常。"""
        if database is not None:
            for s in self.sweeps:
                if s.is_state:
                    continue
                if database.resolve(s.target) is None:
                    raise CalculationError(
                        f"组分 {s.target} 不在数据库 {database.name} 中",
                        f"可选元素：{', '.join(database.display_elements)}",
                    )

    # ---------------------------------------------------------------- 输出
    def build(self, database: Optional[LoadedDatabase] = None) -> dict:
        """转成 pycalphad 的 conditions 字典（离散采样点数组）。"""
        conds: dict = {}
        for sweep in self.sweeps:
            conds[_to_statevar(sweep.target, database)] = sweep.values
        return self._with_fixed(conds, database)

    def build_ranges(self, database: Optional[LoadedDatabase] = None) -> dict:
        """同 :meth:`build`，但均匀扫描用 ``(start, stop, step)`` 区间表示。

        pycalphad 的 ``binplot`` 内部把条件原样交给映射算法，**只认区间三元组**：
        传离散数组会在深处报 ``ValueError: need at least one array to
        concatenate``。等步长的扫描轴在这里还原成区间，非等步长的保持数组。
        """
        conds: dict = {}
        for sweep in self.sweeps:
            var = _to_statevar(sweep.target, database)
            conds[var] = _as_range(sweep.values)
        return self._with_fixed(conds, database)

    def _with_fixed(self, conds: dict, database: Optional[LoadedDatabase]) -> dict:
        """补上固定条件与总摩尔数 N（pycalphad 要求显式给出 N）。"""
        # 固定成分只有 step / isopleth 消费（其余相图类型的自由度
        # 不允许这样钉，避免多余的 X 标量条件把 binplot 弄糊涂）
        allow_comp_fix = self.diagram_type in ("step", "isopleth")
        for target, value in self.fixed.items():
            if _is_swept(self.sweeps, target):
                continue
            if target.upper() in STATE_KEYS or allow_comp_fix:
                conds[_to_statevar(target, database)] = float(value)
        if not _is_swept(self.sweeps, "N"):
            conds.setdefault(v.N, 1.0)
        return conds

    def describe(self) -> str:
        parts = [s.describe() for s in self.sweeps]
        for target, value in self.fixed.items():
            if target.upper() not in STATE_KEYS or not _is_swept(self.sweeps, target):
                parts.append(f"{target}: {value:g}")
        return " | ".join(parts) if parts else "无条件"


def _is_swept(sweeps: Iterable[Sweep], target: str) -> bool:
    up = target.upper()
    return any(s.target.upper() == up for s in sweeps)


def _as_range(values: "np.ndarray"):
    """等步长且不少于 2 点的数组 → (start, stop, step)，否则原样返回。"""
    arr = np.asarray(values, dtype=float)
    if arr.size >= 2:
        step = arr[1] - arr[0]
        if step != 0 and np.allclose(np.diff(arr), step):
            return (float(arr[0]), float(arr[-1]), float(step))
    return values


def _as_samples(raw: Sequence[float], target: str) -> np.ndarray:
    """把 ``(start, stop, step)`` 或显式序列统一成升序采样数组。"""
    arr = np.asarray(list(raw), dtype=float)
    if arr.ndim == 0:
        return arr.reshape(1)
    if arr.size == 3 and (arr[0] != arr[1]):
        # 用户写了 (起, 止, 步) 三重数
        start, stop, step = arr
        if step == 0:
            raise CalculationError(f"维度 {target} 的步长不能为 0")
        n = int(max(1, round((stop - start) / step))) + 1
        return np.linspace(start, start + step * (n - 1), n)
    return arr


def _to_statevar(target: str, database: Optional[LoadedDatabase] = None):
    """``'T'`` → ``v.T``，``'AL'`` → ``v.X('AL')``。"""
    up = target.strip().upper()
    if up == "T":
        return v.T
    if up == "P":
        return v.P
    if up == "N":
        return v.N
    name = target if database is None else (database.resolve(target) or target)
    return v.X(name)


def axis_candidates(
    database: LoadedDatabase,
    elements: Optional[Sequence[str]] = None,
) -> Tuple[List[str], List[str]]:
    """返回 (组分候选, 外部条件候选) 用于 UI 下拉框。

    ``elements`` 是**周期表当前勾选**的元素。传了就只给这些——多元素库
    （如 cost507R 有 20 个元素）若无视勾选把库内全部元素都塞进下拉框，
    用户选了 Ti / V 却还能扫 AL，界面上就成了"选了没用"的假联动。
    不传才回落到 ``display_elements``（换库瞬间、勾选为空时）。
    """
    picked = [str(e).upper() for e in (elements or ())]
    picked = [e for e in picked if database.resolve(e) is not None]
    comps = picked or [e.upper() for e in database.display_elements]
    return comps, list(STATE_KEYS)


def swap_axis(database: LoadedDatabase, target: str) -> str:
    """坐标轴互换时的目标选择：组分与条件之间互相转换。

    注意 pycalphad 的 ``eqplot`` 要求横轴必须是组分（见 ARCHITECTURE T1），
    因此这里只负责命名转换，角色约束由 :meth:`ConditionPlan.validate` 兜底。
    """
    up = target.strip().upper()
    if up in STATE_KEYS and database is not None:
        el = database.display_elements
        if len(el) >= 2:
            return el[0].upper()
    return "T"

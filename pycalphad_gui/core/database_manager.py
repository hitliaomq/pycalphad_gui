"""数据库加载与解析。

职责：
1. 读取 TDB / DAT（pycalphad 会按扩展名自动选解析器）；
2. 抽出**真实元素**、**相列表**及其结构信息；
3. 提供元素符号规范化（周期表里是 ``Al``，TDB 里写的是 ``AL``）；
4. 由"用户在周期表选中的元素"推导"计算用的组分列表"。

解析结果全部放入不可变 dataclass，避免 UI 改动后计算侧读到半更新状态。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from pycalphad import Database

from .diagnostics import CalculationError, diagnose, log_exception
from ..config import ELECTRON_GAS, VACANCY, is_real_element


@dataclass(frozen=True)
class PhaseInfo:
    """单个相的结构摘要。"""

    name: str
    n_sublattices: int
    site_fractions: Tuple[float, ...]
    model_type: str
    constituents: Tuple[Tuple[str, ...], ...] = ()

    @property
    def display(self) -> str:
        return self.name


@dataclass(frozen=True)
class LoadedDatabase:
    """一次加载的完整结果。"""

    path: Path
    name: str
    dbf: Database
    #: 周期表展示用：已剔除 '-'（电荷占位）与 'VA'（空位）
    display_elements: Tuple[str, ...]
    #: 计算可用组分：真实元素 + 空位
    all_elements: Tuple[str, ...]
    #: 相名 → 结构信息
    phases: Dict[str, PhaseInfo]
    species: Tuple[str, ...]
    load_time_s: float
    warnings: Tuple[str, ...] = ()

    # ------------------------------------------------------------------ 符号解析
    def resolve(self, symbol: str) -> Optional[str]:
        """把用户书写的符号映射到库中的实际写法。

        匹配顺序：原样 → 全大写 → 首字母大写，都失败返回 None。
        """
        if not symbol:
            return None
        for candidate in (symbol, symbol.upper(), symbol.capitalize()):
            if candidate in self.all_elements:
                return candidate
        return None

    def normalize_all(self, symbols: Sequence[str]) -> List[str]:
        """批量规范化；无法解析的符号被跳过并记录。"""
        out: List[str] = []
        bad: List[str] = []
        for sym in symbols:
            resolved = self.resolve(sym)
            if resolved is None:
                bad.append(sym)
            elif resolved not in out:
                out.append(resolved)
        if bad:
            raise CalculationError(
                f"元素 {', '.join(bad)} 不在数据库 {self.name} 中",
                f"库内可选元素：{', '.join(self.display_elements)}",
            )
        return out

    def components_for(self, symbols: Sequence[str]) -> List[str]:
        """由选中元素推导计算组分。

        空位（VA）始终并入组分列表：多数 CEF 相模型依赖它作为 endmember，
        缺少时 pycalphad 会把该类相判为不可激活。
        """
        resolved = self.normalize_all(symbols)
        comps = list(resolved)
        if VACANCY in self.all_elements and VACANCY not in comps:
            comps.append(VACANCY)
        if not comps:
            raise CalculationError("尚未选择任何元素", "请先在元素周期表中勾选元素")
        return comps

    def components_safe(self, symbols: Sequence[str]) -> Tuple[List[str], List[str]]:
        """``components_for`` 的宽容版，永不抛异常。

        返回 ``(可用组分, 被忽略的符号)``。周期表允许勾选库外元素（灰显但仍
        可点），直接走 ``components_for`` 会抛 ``CalculationError``；而这个
        调用发生在 Qt 槽里，PyQt6 对"槽里逃逸的异常"是 **直接 abort 进程**
        （不是打印日志）。所以 UI 联动一律走这里，坏的符号单独回报给用户。
        """
        comps: List[str] = []
        ignored: List[str] = []
        for sym in symbols or ():
            resolved = self.resolve(sym)
            if resolved is None:
                ignored.append(str(sym))
            elif resolved == VACANCY:
                continue  # 空位不占"用户选了什么"，也不该被当成选错的符号回报
            elif resolved not in comps:
                comps.append(resolved)
        # 空位只在真的选到了元素时才并入：一个元素都没选（或只选了空位）时
        # 返回 [VA] 会被下游当成"有效体系"放过去，算出一个空壳
        if comps and VACANCY in self.all_elements and VACANCY not in comps:
            comps.append(VACANCY)
        return comps, ignored

    def comps_of(self, symbols: Sequence[str]) -> List[str]:
        """宽容版：只返回可用组分，被忽略的静默丢弃。"""
        return self.components_safe(symbols)[0]

    def sweep_candidates(self, symbols: Sequence[str]) -> List[str]:
        """可作扫描轴 / 组分输入的元素（已规范化、剔除空位与重复）。

        空位（VA）不能当摩尔分数扫描，也不能做摩尔分数输入，必须滤掉。
        """
        out: List[str] = []
        for sym in symbols or ():
            resolved = self.resolve(sym)
            if resolved is None or resolved == VACANCY:
                continue
            if resolved not in out:
                out.append(resolved)
        return out

    def is_available(self, symbol: str) -> bool:
        return self.resolve(symbol) is not None

    @property
    def phase_names(self) -> List[str]:
        return list(self.phases.keys())


# --------------------------------------------------------------------- 解析实现
def _infer_model_type(phase, sublattices: Sequence[float]) -> str:
    """从子格子数与模型提示推断相模型类型，仅用于界面展示。"""
    hints = getattr(phase, "model_hints", {}) or {}
    typedefs = hints.get("typedefs") or ()
    if typedefs:
        return str(typedefs[0])
    if len(sublattices) == 1:
        return "Substitution"
    return f"CEF({len(sublattices)} sublattices)"


def _extract_phases(dbf: Database) -> Dict[str, PhaseInfo]:
    phases: Dict[str, PhaseInfo] = {}
    for name, phase in dbf.phases.items():
        sublats = tuple(float(s) for s in (phase.sublattices or ()))
        constituents = tuple(
            tuple(sorted(str(sp) for sp in sub))
            for sub in (phase.constituents or ())
        )
        phases[str(name)] = PhaseInfo(
            name=str(name),
            n_sublattices=len(sublats),
            site_fractions=sublats,
            model_type=_infer_model_type(phase, sublats),
            constituents=constituents,
        )
    return phases


def _extract_elements(dbf: Database) -> Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]]:
    """返回 (展示元素, 全部元素, 警告)。"""
    warnings: List[str] = []
    raw = {str(e) for e in getattr(dbf, "elements", ())}
    if not raw:
        raise CalculationError(
            "数据库未解析出任何元素",
            "文件可能不是有效的 TDB/DAT 格式",
        )

    # 用通用规则筛掉 VA / /- / AL/+ 等伪组分与电荷物种，只留真实元素
    real = {e for e in raw if is_real_element(e)}
    dropped = sorted(raw - real - {VACANCY})
    if dropped:
        warnings.append(
            f"已忽略非元素组分 {', '.join(dropped)}（空位与电荷占位不参与周期表展示）"
        )
    if VACANCY not in raw:
        warnings.append(f"库中未显式声明空位（{VACANCY}），计算时将以隐式方式处理")

    display = tuple(sorted(real))
    all_el = tuple(sorted(raw))
    return display, all_el, tuple(warnings)


def load_database(path: Union[str, Path]) -> LoadedDatabase:
    """加载数据库文件。

    Parameters
    ----------
    path
        .tdb / .dat 文件路径。

    Raises
    ------
    CalculationError
        文件不存在、无法读取或解析失败。
    """
    path = Path(path)
    t0 = time.perf_counter()

    if not path.exists():
        raise CalculationError(f"文件不存在：{path.name}", str(path))

    try:
        # Database() 会按扩展名选择 tdb / dat 解析器
        dbf = Database(str(path))
    except CalculationError:
        raise
    except Exception as exc:  # noqa: BLE001 - 解析器抛任意异常
        log_exception(exc, f"解析数据库 {path.name}")
        raise diagnose(exc, f"解析数据库 {path.name}") from exc

    display, all_el, warnings = _extract_elements(dbf)
    phases = _extract_phases(dbf)

    if not phases:
        raise CalculationError(
            f"数据库 {path.name} 中没有解析到任何相",
            "请确认该文件是 Thermo-Calc 的 TDB 格式",
        )

    return LoadedDatabase(
        path=path,
        name=path.name,
        dbf=dbf,
        display_elements=display,
        all_elements=all_el,
        phases=phases,
        species=tuple(sorted(str(s) for s in getattr(dbf, "species", ()))),
        load_time_s=time.perf_counter() - t0,
        warnings=warnings,
    )


def filter_phases(
    database: LoadedDatabase,
    enabled: Sequence[str],
) -> List[str]:
    """把 UI 的相选中态转成参与计算的相名列表。

    这里**只做校验与排序**，绝不隐式增删相：元素是否能让某个相激活，
    由 pycalphad 的相模型自己判定，GUI 插手反而会造成"图上有但算不出来"。

    Raises
    ------
    CalculationError
        选中集合为空，或含库中不存在的相名。
    """
    names = list(enabled) if enabled else []
    if not names:
        raise CalculationError("没有选中任何相", "请至少启用一个相")

    unknown = [n for n in names if n not in database.phases]
    if unknown:
        raise CalculationError(
            f"相 {', '.join(unknown)} 在当前数据库中不存在",
            f"可选相：{', '.join(database.phase_names[:20])}"
            + ("..." if len(database.phase_names) > 20 else ""),
        )
    return sorted(set(names))

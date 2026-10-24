"""内置元素周期表数据。

不依赖 ``mendeleev`` / ``periodictable`` 等第三方包，避免额外的安装与许可问题。
数据覆盖 118 个元素，包含：原子序数、元素符号、中文名、周期表网格坐标（列, 行）、
元素类别。

超重元素（Z >= 104）的中文名为空，由 UI 回退显示元素符号——这些生僻汉字
（如"𬬻"）在常规字体中普遍缺字，强行渲染会出现豆腐块。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# 类别常量，UI 用它决定单元格背景色
CAT_ALKALI = "alkali"
CAT_ALKALINE = "alkaline"
CAT_TRANSITION = "transition"
CAT_POST = "post"
CAT_METALLOID = "metalloid"
CAT_NONMETAL = "nonmetal"
CAT_HALOGEN = "halogen"
CAT_NOBLE = "noble"
CAT_LANTHANIDE = "lanthanide"
CAT_ACTINIDE = "actinide"
CAT_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# (原子序数, 符号, 中文名, 列, 行, 类别)
# 行 1~7 为主周期表行；行 9/10 用于镧系与锕系（f-block 单独抽行显示）
# ---------------------------------------------------------------------------
_ELEMENT_TABLE: Tuple[Tuple[int, str, str, int, int, str], ...] = (
    # ── 第 1 周期 ────────────────────────────────────────────────────────
    (1, "H", "氢", 1, 1, CAT_NONMETAL),
    (2, "He", "氦", 18, 1, CAT_NOBLE),
    # ── 第 2 周期 ────────────────────────────────────────────────────────
    (3, "Li", "锂", 1, 2, CAT_ALKALI),
    (4, "Be", "铍", 2, 2, CAT_ALKALINE),
    (5, "B", "硼", 13, 2, CAT_METALLOID),
    (6, "C", "碳", 14, 2, CAT_NONMETAL),
    (7, "N", "氮", 15, 2, CAT_NONMETAL),
    (8, "O", "氧", 16, 2, CAT_NONMETAL),
    (9, "F", "氟", 17, 2, CAT_HALOGEN),
    (10, "Ne", "氖", 18, 2, CAT_NOBLE),
    # ── 第 3 周期 ────────────────────────────────────────────────────────
    (11, "Na", "钠", 1, 3, CAT_ALKALI),
    (12, "Mg", "镁", 2, 3, CAT_ALKALINE),
    (13, "Al", "铝", 13, 3, CAT_POST),
    (14, "Si", "硅", 14, 3, CAT_METALLOID),
    (15, "P", "磷", 15, 3, CAT_NONMETAL),
    (16, "S", "硫", 16, 3, CAT_NONMETAL),
    (17, "Cl", "氯", 17, 3, CAT_HALOGEN),
    (18, "Ar", "氩", 18, 3, CAT_NOBLE),
    # ── 第 4 周期 ────────────────────────────────────────────────────────
    (19, "K", "钾", 1, 4, CAT_ALKALI),
    (20, "Ca", "钙", 2, 4, CAT_ALKALINE),
    (21, "Sc", "钪", 3, 4, CAT_TRANSITION),
    (22, "Ti", "钛", 4, 4, CAT_TRANSITION),
    (23, "V", "钒", 5, 4, CAT_TRANSITION),
    (24, "Cr", "铬", 6, 4, CAT_TRANSITION),
    (25, "Mn", "锰", 7, 4, CAT_TRANSITION),
    (26, "Fe", "铁", 8, 4, CAT_TRANSITION),
    (27, "Co", "钴", 9, 4, CAT_TRANSITION),
    (28, "Ni", "镍", 10, 4, CAT_TRANSITION),
    (29, "Cu", "铜", 11, 4, CAT_TRANSITION),
    (30, "Zn", "锌", 12, 4, CAT_TRANSITION),
    (31, "Ga", "镓", 13, 4, CAT_POST),
    (32, "Ge", "锗", 14, 4, CAT_METALLOID),
    (33, "As", "砷", 15, 4, CAT_METALLOID),
    (34, "Se", "硒", 16, 4, CAT_NONMETAL),
    (35, "Br", "溴", 17, 4, CAT_HALOGEN),
    (36, "Kr", "氪", 18, 4, CAT_NOBLE),
    # ── 第 5 周期 ────────────────────────────────────────────────────────
    (37, "Rb", "铷", 1, 5, CAT_ALKALI),
    (38, "Sr", "锶", 2, 5, CAT_ALKALINE),
    (39, "Y", "钇", 3, 5, CAT_TRANSITION),
    (40, "Zr", "锆", 4, 5, CAT_TRANSITION),
    (41, "Nb", "铌", 5, 5, CAT_TRANSITION),
    (42, "Mo", "钼", 6, 5, CAT_TRANSITION),
    (43, "Tc", "锝", 7, 5, CAT_TRANSITION),
    (44, "Ru", "钌", 8, 5, CAT_TRANSITION),
    (45, "Rh", "铑", 9, 5, CAT_TRANSITION),
    (46, "Pd", "钯", 10, 5, CAT_TRANSITION),
    (47, "Ag", "银", 11, 5, CAT_TRANSITION),
    (48, "Cd", "镉", 12, 5, CAT_TRANSITION),
    (49, "In", "铟", 13, 5, CAT_POST),
    (50, "Sn", "锡", 14, 5, CAT_POST),
    (51, "Sb", "锑", 15, 5, CAT_METALLOID),
    (52, "Te", "碲", 16, 5, CAT_METALLOID),
    (53, "I", "碘", 17, 5, CAT_HALOGEN),
    (54, "Xe", "氙", 18, 5, CAT_NOBLE),
    # ── 第 6 周期（La→Lu 抽至 f-block 行） ───────────────────────────────
    (55, "Cs", "铯", 1, 6, CAT_ALKALI),
    (56, "Ba", "钡", 2, 6, CAT_ALKALINE),
    (72, "Hf", "铪", 4, 6, CAT_TRANSITION),
    (73, "Ta", "钽", 5, 6, CAT_TRANSITION),
    (74, "W", "钨", 6, 6, CAT_TRANSITION),
    (75, "Re", "铼", 7, 6, CAT_TRANSITION),
    (76, "Os", "锇", 8, 6, CAT_TRANSITION),
    (77, "Ir", "铱", 9, 6, CAT_TRANSITION),
    (78, "Pt", "铂", 10, 6, CAT_TRANSITION),
    (79, "Au", "金", 11, 6, CAT_TRANSITION),
    (80, "Hg", "汞", 12, 6, CAT_TRANSITION),
    (81, "Tl", "铊", 13, 6, CAT_POST),
    (82, "Pb", "铅", 14, 6, CAT_POST),
    (83, "Bi", "铋", 15, 6, CAT_POST),
    (84, "Po", "钋", 16, 6, CAT_METALLOID),
    (85, "At", "砹", 17, 6, CAT_HALOGEN),
    (86, "Rn", "氡", 18, 6, CAT_NOBLE),
    # ── 第 7 周期（Ac→Lr 抽至 f-block 行） ───────────────────────────────
    (87, "Fr", "钫", 1, 7, CAT_ALKALI),
    (88, "Ra", "镭", 2, 7, CAT_ALKALINE),
    (104, "Rf", "", 4, 7, CAT_TRANSITION),
    (105, "Db", "", 5, 7, CAT_TRANSITION),
    (106, "Sg", "", 6, 7, CAT_TRANSITION),
    (107, "Bh", "", 7, 7, CAT_TRANSITION),
    (108, "Hs", "", 8, 7, CAT_TRANSITION),
    (109, "Mt", "", 9, 7, CAT_UNKNOWN),
    (110, "Ds", "", 10, 7, CAT_UNKNOWN),
    (111, "Rg", "", 11, 7, CAT_UNKNOWN),
    (112, "Cn", "", 12, 7, CAT_UNKNOWN),
    (113, "Nh", "", 13, 7, CAT_UNKNOWN),
    (114, "Fl", "", 14, 7, CAT_UNKNOWN),
    (115, "Mc", "", 15, 7, CAT_UNKNOWN),
    (116, "Lv", "", 16, 7, CAT_UNKNOWN),
    (117, "Ts", "", 17, 7, CAT_HALOGEN),
    (118, "Og", "", 18, 7, CAT_NOBLE),
)

_LANTHANIDES: Tuple[Tuple[int, str, str], ...] = (
    (57, "La", "镧"), (58, "Ce", "铈"), (59, "Pr", "镨"), (60, "Nd", "钕"),
    (61, "Pm", "钷"), (62, "Sm", "钐"), (63, "Eu", "铕"), (64, "Gd", "钆"),
    (65, "Tb", "铽"), (66, "Dy", "镝"), (67, "Ho", "钬"), (68, "Er", "铒"),
    (69, "Tm", "铥"), (70, "Yb", "镱"), (71, "Lu", "镥"),
)

_ACTINIDES: Tuple[Tuple[int, str, str], ...] = (
    (89, "Ac", "锕"), (90, "Th", "钍"), (91, "Pa", "镤"), (92, "U", "铀"),
    (93, "Np", "镎"), (94, "Pu", "钚"), (95, "Am", "镅"), (96, "Cm", "锔"),
    (97, "Bk", "锫"), (98, "Cf", "锎"), (99, "Es", "锿"), (100, "Fm", "镄"),
    (101, "Md", "钔"), (102, "No", "锘"), (103, "Lr", "铹"),
)


@dataclass(frozen=True)
class ElementInfo:
    """单个元素的静态信息。"""

    number: int
    symbol: str
    name_cn: str
    col: int
    row: int
    category: str

    @property
    def label(self) -> str:
        """用于 UI 显示的文本：优先中文名，缺失时回退到英文符号。"""
        return self.name_cn or self.symbol

    @property
    def tooltip(self) -> str:
        return f"{self.number}. {self.symbol} {self.label}"


def _build() -> Dict[int, ElementInfo]:
    """把三张表合并成 {原子序数: ElementInfo}。"""
    table: Dict[int, ElementInfo] = {}
    for number, symbol, name_cn, col, row, category in _ELEMENT_TABLE:
        table[number] = ElementInfo(number, symbol, name_cn, col, row, category)
    # 镧系：列 3~17，行 9
    for idx, (number, symbol, name_cn) in enumerate(_LANTHANIDES):
        table[number] = ElementInfo(number, symbol, name_cn, 3 + idx, 9, CAT_LANTHANIDE)
    # 锕系：列 3~17，行 10
    for idx, (number, symbol, name_cn) in enumerate(_ACTINIDES):
        table[number] = ElementInfo(number, symbol, name_cn, 3 + idx, 10, CAT_ACTINIDE)
    return table


ELEMENTS: Dict[int, ElementInfo] = _build()

#: 元素符号 → 原子序数，便于按用户输入的符号反查
SYMBOL_TO_Z: Dict[str, int] = {info.symbol: z for z, info in ELEMENTS.items()}


def get_by_symbol(symbol: str) -> Optional[ElementInfo]:
    """按符号取元素信息；大小写不敏感，找不到返回 None。

    ``SYMBOL_TO_Z`` 的键是表格里的原始符号（``Fe`` 这种混合大小写），
    所以先按原样查一次，查不到再退回去查大写 —— 只查大写会把 Fe/Zn 这类
    当成"未知元素"。
    """
    key = symbol.strip()
    info = ELEMENTS.get(SYMBOL_TO_Z.get(key, -1))
    if info is None:
        info = ELEMENTS.get(SYMBOL_TO_Z.get(key.upper(), -1))
    return info


def layout_rows() -> List[Tuple[int, List[Optional[ElementInfo]]]]:
    """生成周期表的行布局，供 UI 逐行摆放控件。

    返回 [(行号, [该行每个格子或 None]), ...]。行号 8 是周期表里的空隙，
    保留它以便 f-block 单独成行的视觉对齐。
    """
    rows: Dict[int, List[Optional[ElementInfo]]] = {}
    for info in ELEMENTS.values():
        row = rows.setdefault(info.row, [None] * 19)
        # 下标 0 空置，让列号与真实列号对齐
        while len(row) <= info.col:
            row.append(None)
        row[info.col] = info

    ordered: List[Tuple[int, List[Optional[ElementInfo]]]] = []
    for row_no in sorted(rows):
        cells = rows[row_no]
        while len(cells) < 19:
            cells.append(None)
        ordered.append((row_no, cells))
    return ordered


def known_symbols() -> List[str]:
    """全部已知元素符号，按原子序数排序。"""
    return [ELEMENTS[z].symbol for z in sorted(ELEMENTS)]

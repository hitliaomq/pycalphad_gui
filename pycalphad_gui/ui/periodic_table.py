"""紧凑元素周期表。

设计取舍：相图窗口才是主角，所以周期表必须**克制**：

* 每格只显示元素符号（原子序数、中文名放 tooltip），格子缩到 ``24 x 22``；
* **所有元素始终显示**：库内元素高亮（彩色底 + 蓝色描边），库外元素灰化
  （但仍然可选——有些数据库的元素列表不全，用户比程序更清楚）；
* ``VA``（空位）与 ``/-``（电子气）两个伪元素放在第 1 周期的空白格
  （列 7、8），与 Thermo-Calc / TDB 的物种写法一致，CEF 相模型常用；
* 全表 18 列宽约 430px，高度按内容行数给足，**默认不需要滚动**即可看全。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import elements as elem
from .. import i18n
from ..config import ELECTRON_GAS, VACANCY
from .theme import (
    CELL_UNSELECTED,
    PALETTE,
    SELECTED_CELL_BG,
    SELECTED_CELL_TEXT,
)

#: 单元格尺寸（像素）。想更紧凑改这里就够了。
CELL_W = 24
CELL_H = 22
#: 类别 → 底色（浅到几乎透明，仅作分组暗示）
_CATEGORY_COLORS: Dict[str, str] = {
    elem.CAT_ALKALI: "#ffe9e9",
    elem.CAT_ALKALINE: "#fff4e4",
    elem.CAT_TRANSITION: "#eaf6e6",
    elem.CAT_POST: "#eceefb",
    elem.CAT_METALLOID: "#eef3fb",
    elem.CAT_NONMETAL: "#e7f8f3",
    elem.CAT_HALOGEN: "#f4eefb",
    elem.CAT_NOBLE: "#f0f0f2",
    elem.CAT_LANTHANIDE: "#fdf6e3",
    elem.CAT_ACTINIDE: "#fdeeee",
    elem.CAT_UNKNOWN: "#f6f6f6",
}
#: 库内元素描边（淡蓝，一眼可辨"这个库里有它"）
_AVAILABLE_BORDER = "#8fb0f2"
#: 库外元素的灰化配色
_MUTED_BG = "#eef0f4"
_MUTED_TEXT = "#9aa2b1"
#: 伪元素（VA / /-）底色
_PSEUDO_BG = "#eef4ff"

#: 单元格样式模板。刻意用 ``__占位符__`` 而不是 f-string / str.format ——
#: QSS 里全是 ``{`` / ``}``，再叠一层转义既难读又容易写错（``{{bg}}`` 那种）。
_CELL_STYLE_TEMPLATE = """
QToolButton {
    border: 1px solid __BORDER__;
    border-radius: 4px;
    background: __BG__;
    color: __TEXT__;
    font-size: 9px;
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-weight: 600;
    padding: 0;
    margin: 0;
}
QToolButton:hover { border: 1px solid __ACCENT__; }
QToolButton:checked {
    background: __SEL_BG__;
    color: __SEL_TEXT__;
    border: 1px solid __SEL_BG__;
}
"""


def _cell_style(bg: str, text: str, border: str) -> str:
    """按底色 / 文字 / 描边生成该格子的样式表。"""
    replacements = {
        "__BORDER__": border,
        "__TEXT__": text,
        "__BG__": bg,
        "__ACCENT__": PALETTE["accent"],
        "__SEL_BG__": SELECTED_CELL_BG,
        "__SEL_TEXT__": SELECTED_CELL_TEXT,
    }
    style = _CELL_STYLE_TEMPLATE
    for token, value in replacements.items():
        style = style.replace(token, value)
    return style


#: 伪元素定义：(符号, 显示文本, tooltip, 表格位置 (行, 列))
#: 放在第 1 周期的空白格（列 7、8）—— 用户指定位置，一眼就能看到，
#: 也不会和主表元素挤在一起。
_PSEUDO_CELLS: Tuple[Tuple[str, str, str, Tuple[int, int]], ...] = (
    (
        VACANCY,
        VACANCY,
        f"{VACANCY} — 空位（Vacancy）：CEF 相模型亚晶格中的空位占据",
        (1, 7),
    ),
    (
        ELECTRON_GAS,
        ELECTRON_GAS,
        f"{ELECTRON_GAS} — 电子气（Electron gas）：离子/电子相模型物种",
        (1, 8),
    ),
)


class PeriodicTableWidget(QWidget):
    """周期表控件。

    Signals
    -------
    selection_changed
        选中集合变化时发出，参数为选中的元素符号列表。
    """

    selection_changed = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._buttons: Dict[str, QToolButton] = {}
        #: 每个符号对应的"库内"基础样式 (bg, text, border)，刷新可用性时复用
        self._base_style: Dict[str, Tuple[str, str, str]] = {}
        #: 原始 tooltip（不带"库内/库外"后缀），避免刷新时反复拼接
        self._base_tooltip: Dict[str, str] = {}
        #: 元素格子的 tooltip 素材 (原子序数, 符号, 中文名)；伪元素为 None。
        #: 单独存一份是为了切语言时能重建 tooltip——元素名是**单字**，
        #: 片段替换够不着（单字键会误伤普通句子，所以被排除在片段表外）。
        self._tooltip_src: Dict[str, Optional[Tuple[int, str, str]]] = {}
        self._available: Set[str] = set()
        self._selected: Set[str] = set()
        #: Shift 框选的锚点元素符号
        self._anchor: Optional[str] = None
        self._build_ui()

    # ---------------------------------------------------------------- 构建
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        hint = QLabel("元素（蓝框＝库内 · 这里勾什么，各页就只认什么 · Shift+点击框选范围）")
        hint.setObjectName("hint")
        hint.setStyleSheet("color: #7a8494; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # 当前勾选摘要 + 清空按钮：T54 的教训是"选中集里有个看不见的 Al"，
        # 状态栏小小一角根本注意不到。勾了什么必须摆在周期表正上方。
        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        self._summary = QLabel("未勾选", self)
        self._summary.setStyleSheet(
            "color: #2f6feb; font-size: 11px; font-weight: 600;"
        )
        self._summary.setWordWrap(True)
        btn_clear = QPushButton("清空", self)
        # 别写死宽度：全局按钮 QSS 的 padding 6px 14px 会把 44px 挤得
        # 只剩一个字（用户实测只见半个"清"）
        btn_clear.setObjectName("iconBtn")
        btn_clear.setFixedWidth(56)
        btn_clear.setToolTip("取消所有已勾选的元素")
        btn_clear.clicked.connect(self.clear_selection)
        summary_row.addWidget(self._summary, 1)
        summary_row.addWidget(btn_clear)
        layout.insertLayout(layout.count() - 1, summary_row)

        grid = QGridLayout()
        grid.setSpacing(1)
        grid.setContentsMargins(0, 0, 0, 0)

        self._group = QButtonGroup(self)
        self._group.setExclusive(False)
        self._group.buttonClicked.connect(self._on_button_clicked)

        # layout_rows() 给出 (行号, cells)，cells 按列号索引（0 号位留空），
        # 元素对象本身即该格内容，空格子是 None。注意别再解包成 (列, 元素)。
        occupied: Set[Tuple[int, int]] = set()
        max_row = 0
        for row, cells in elem.layout_rows():
            max_row = max(max_row, row)
            for col, info in enumerate(cells):
                if info is None:
                    continue
                button = self._make_button(
                    info.symbol,
                    info.symbol,
                    info.tooltip,
                    _CATEGORY_COLORS.get(info.category, "#f6f6f6"),
                )
                self._tooltip_src[info.symbol] = (info.number, info.symbol, info.name_cn)
                grid.addWidget(button, row, col)
                occupied.add((row, col))

        # 第 1 周期空白格：放 VA（空位）与 /-（电子气）两个伪元素
        for symbol, text, tooltip, (row, col) in _PSEUDO_CELLS:
            button = self._make_button(symbol, text, tooltip, _PSEUDO_BG)
            self._tooltip_src[symbol] = None          # 伪元素：整条 tooltip 都在词典里
            grid.addWidget(button, row, col)
            occupied.add((row, col))

        wrapper = QWidget(self)
        wrapper.setLayout(grid)
        scroller = QScrollArea(self)
        scroller.setWidgetResizable(False)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroller.setWidget(wrapper)
        scroller.setFrameShape(QScrollArea.Shape.NoFrame)
        # 宽度也要给足（18 列 + 17 个列距），否则冒出水平滚动条把 He 列截掉
        scroller.setMinimumWidth(CELL_W * 18 + grid.horizontalSpacing() * 17 + 4)
        # 高度按内容给足（主表 7 行 + 镧系 / 锕系 2 行，再留出边距与水平
        # 滚动条的余量）—— 面板默认就能看全整个周期表，不用再滚鼠标。
        scroller.setMinimumHeight(max_row * (CELL_H + grid.verticalSpacing()) + 16)
        self._scroller = scroller
        layout.addWidget(scroller, 1)

    def _make_button(self, symbol: str, text: str, tooltip: str, bg: str) -> QToolButton:
        button = QToolButton()
        # 只留符号，其余信息全走 tooltip —— 这是把格子压小的关键
        button.setText(text)
        button.setCheckable(True)
        button.setFixedSize(CELL_W, CELL_H)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setToolTip(tooltip)
        self._base_style[symbol] = (bg, CELL_UNSELECTED["text"], CELL_UNSELECTED["border"])
        self._base_tooltip[symbol] = tooltip
        button.setStyleSheet(
            _cell_style(bg, CELL_UNSELECTED["text"], CELL_UNSELECTED["border"])
        )
        self._group.addButton(button)
        self._buttons[symbol] = button
        return button

    # ---------------------------------------------------------------- 交互
    def _on_button_clicked(self, button: QAbstractButton) -> None:
        symbol = self._symbol_of(button)
        if not symbol:
            return
        # 选中集统一存大写；按钮符号是混合大小写（'Al'/'Ti'），直接存会跟
        # set_selection 存的大写集合对不上（T54 的根源之一）
        key = symbol.upper()

        # Shift + 点击：以上次点击的元素为锚点，框选整个区间。
        # 注意：buttonClicked 抛出的是 QAbstractButton（只有 isChecked()），
        # 没有 modifiers() —— 那玩意在 QMouseEvent 上。取修饰键要去问
        # 全局键盘状态：键盘触发（空格 / Enter）时也没有点击事件，同样要用它。
        shift = bool(QApplication.keyboardModifiers()
                     & Qt.KeyboardModifier.ShiftModifier)
        if shift and self._anchor:
            self._select_range(self._anchor, symbol, button.isChecked())
            self._anchor = symbol
            self.selection_changed.emit(sorted(self._selected))
            return

        self._anchor = symbol
        # 用 isChecked() 而不是 checkState()：非三态按钮上后者在 Qt6 没有这个属性
        if not button.isChecked():
            self._selected.discard(key)
        else:
            self._selected.add(key)
        self.selection_changed.emit(sorted(self._selected))

    def _select_range(self, first: str, last: str, checked: bool) -> None:
        """按原子序数区间批量勾选/取消。

        :meth:`~pycalphad_gui.elements.SYMBOL_TO_Z` 用的是表格里**原始**的符号
        （``Fe`` 这种混合大小写），再拿 ``.upper()`` 去查会 KeyError，而这里
        又把它收在了 ``except`` 里 —— 表现就是"Shift 框选点了半天没反应"。
        所以按符号原样查；顺带把查不到的符号跳过，而不是让整段区间作废
        （伪元素 VA / /- 本来就不在 ELEMENTS 里）。
        """
        z1 = elem.SYMBOL_TO_Z.get(first)
        z2 = elem.SYMBOL_TO_Z.get(last)
        if z1 is None or z2 is None:
            return
        low, high = sorted((z1, z2))
        for z in range(low, high + 1):
            info = elem.ELEMENTS.get(z)
            if info is None:
                continue
            btn = self._buttons.get(info.symbol)
            if btn is None:
                continue
            btn.setChecked(checked)
            if checked:
                self._selected.add(info.symbol.upper())
            else:
                self._selected.discard(info.symbol.upper())

    def _update_summary(self) -> None:
        """刷新"当前勾选"摘要行。勾选集统一是大写，展示时转回常规写法。"""
        if not self._selected:
            self._summary.setText(i18n.tr("未勾选"))
            return
        # 按原子序数排（Al 在 Ti 前面），展示用常规大小写；VA / /- 保持原样，
        # "Va" 会被当成钒看
        order = sorted(
            self._selected,
            key=lambda s: (elem.SYMBOL_TO_Z.get(s.capitalize(), 999), s),
        )
        pretty = [s if s in (VACANCY, ELECTRON_GAS) else s.capitalize() for s in order]
        self._summary.setText(i18n.tr("已勾选：") + " + ".join(pretty))

    def _symbol_of(self, button: QAbstractButton) -> Optional[str]:
        for symbol, btn in self._buttons.items():
            if btn is button:
                return symbol
        return None

    # ---------------------------------------------------------------- 外部接口
    def set_available(self, symbols: Sequence[str]) -> None:
        """按当前数据库刷新高亮：库内描蓝边，库外灰化但**不禁用、不隐藏**。

        不改动已有选中 —— 用户可能就是想先选好元素再换库。
        """
        self._available = {s.upper() for s in symbols}
        for symbol, button in self._buttons.items():
            base = self._base_style.get(symbol, ("#f6f6f6", CELL_UNSELECTED["text"],
                                                 CELL_UNSELECTED["border"]))
            in_db = symbol.upper() in self._available
            if in_db:
                bg, text, border = base[0], base[1], _AVAILABLE_BORDER
            else:
                bg, text, border = _MUTED_BG, _MUTED_TEXT, CELL_UNSELECTED["border"]
            button.setStyleSheet(_cell_style(bg, text, border))
            button.setToolTip(self._tooltip_for(symbol, in_db))

    def _tooltip_for(self, symbol: str, in_db: bool) -> str:
        base = self._base_tooltip.get(symbol, symbol)
        suffix = i18n.tr("库内可用" if in_db
                        else "库内不含该元素（仍可尝试选择）")
        return f"{base} · {suffix}"

    def retranslate(self) -> None:
        """切换语言时重建 tooltip 与摘要行。

        元素名是**单字**（"铁"、"钛"），而单字键被排除在片段替换之外
        （否则"是"/"相"这类字会去咬任何一句没收录的中文），所以这里
        必须按 ``_tooltip_src`` 显式重拼，不能指望整树遍历。
        """
        for symbol, src in self._tooltip_src.items():
            if src is None:
                self._base_tooltip[symbol] = i18n.tr(self._base_tooltip.get(symbol, ""))
            else:
                number, sym, name_cn = src
                self._base_tooltip[symbol] = f"{number}. {sym} {i18n.tr(name_cn) or sym}"
        for symbol, button in self._buttons.items():
            button.setToolTip(self._tooltip_for(symbol, symbol.upper() in self._available))
        self._update_summary()

    def set_selection(self, symbols: Sequence[str]) -> None:
        """程序化设置选中态，不触发 ``selection_changed``。

        T54：按钮符号是混合大小写（``Al`` / ``Ti``），选中集是大写。
        以前直接 ``symbol in self._selected``，两字母元素永远比不中——
        **AL 留在选中集里、按钮却没点亮**，用户看不到它，状态栏与各面板
        的候选却全被它污染。比较前必须统一大写。
        """
        self._selected = {s.upper() for s in symbols}
        for symbol, button in self._buttons.items():
            button.setChecked(symbol.upper() in self._selected)
        self._update_summary()

    def selection(self) -> List[str]:
        """返回当前选中的元素符号（大写）。"""
        return sorted(self._selected)

    def clear_selection(self) -> None:
        for button in self._buttons.values():
            button.setChecked(False)
        self._selected.clear()
        self._update_summary()
        self.selection_changed.emit([])

    def select_all_available(self) -> None:
        for symbol, button in self._buttons.items():
            if symbol.upper() in self._available:
                button.setChecked(True)
                self._selected.add(symbol.upper())
        self._update_summary()
        self.selection_changed.emit(sorted(self._selected))

    def select_range(self, first: str, last: str) -> None:
        """按原子序数区间批量勾选。"""
        self._select_range(first, last, True)
        self._update_summary()
        self.selection_changed.emit(sorted(self._selected))


__all__ = ["PeriodicTableWidget", "CELL_W", "CELL_H"]

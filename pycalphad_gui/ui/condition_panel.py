"""计算条件设置面板。

支持动态添加"扫描维度"，从而同时覆盖二元图（1 组分 + 1 外部条件）与
三元等温截面（2 组分、0 外部条件）两类条件组合；条件是否满足具体相图
类型由 :class:`~core.conditions.ConditionPlan.validate` 统一裁决。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import DEFAULT_P, DEFAULT_T_RANGE, DEFAULT_X_RANGE, DIAGRAM_LABELS, STATE_VARS
from .spinboxes import DisplaySpin
from .. import i18n

#: 单个扫描维度的点数上限，超过会让界面长时间无响应
MAX_SAMPLES = 5000


class SweepRow(QWidget):
    """一个扫描维度：变量 + 起点 + 终点 + 步长。"""

    removed = pyqtSignal(object)

    def __init__(self, targets: Sequence[str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._targets = list(targets)
        #: 目标意图。组合框还没填充候选项时（构造初期）``set_target`` 无法真正
        #: 选中，先把意图记在这里，等 ``set_candidates`` 兑现，避免"选中项被抹掉"。
        self._preferred = ""
        # 两行式：一行塞"下拉 + 3 个数字框 + 删除"的最小宽是各项相加，
        # 右侧面板（≈屏宽 20%）根本放不下——窄面板下必须允许换行堆叠
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        top_row = QHBoxLayout()
        self.var = QComboBox(self)
        self.var.addItems(self._targets)
        top_row.addWidget(self.var, 1)
        layout.addLayout(top_row)

        num_row = QHBoxLayout()
        num_row.setSpacing(4)

        self.start = DisplaySpin(3, self)
        self.start.setRange(-1e4, 1e4)
        self.start.setDecimals(4)
        self.start.setSingleStep(0.01)
        self.start.setValue(float(DEFAULT_X_RANGE[0]))
        self.start.setMaximumWidth(120)
        num_row.addWidget(self.start, 1)

        self.stop = DisplaySpin(3, self)
        self.stop.setRange(-1e4, 1e4)
        self.stop.setDecimals(4)
        self.stop.setSingleStep(0.01)
        self.stop.setValue(float(DEFAULT_X_RANGE[1]))
        self.stop.setMaximumWidth(120)
        num_row.addWidget(self.stop, 1)

        self.step = DisplaySpin(3, self)
        self.step.setRange(1e-6, 1e4)
        self.step.setDecimals(4)
        self.step.setSingleStep(0.01)
        self.step.setValue(float(DEFAULT_X_RANGE[2]))
        self.step.setMaximumWidth(120)
        num_row.addWidget(self.step, 1)
        layout.addLayout(num_row)

        remove = QPushButton("×", self)
        remove.setObjectName("iconBtn")
        remove.setFixedWidth(26)
        remove.setToolTip(i18n.tr("删除该扫描维度"))
        remove.clicked.connect(lambda: self.removed.emit(self))
        top_row.addWidget(remove)

        # 外部条件通常不需要修改起止，视觉上弱化
        self.var.currentTextChanged.connect(self._on_target_changed)

    def _on_target_changed(self, text: str) -> None:
        # 状态变量（T / P / N）只是换一套默认起止值，**不能禁用输入框**：
        # 二元相图恰恰要扫温度，禁用了用户就没法调温度范围（实测反馈的 bug）。
        # 显示位数跟量纲走：温度 1 位、压强 0 位、成分 3 位（存储精度不变）
        key = text.strip().upper()
        disp = 1 if key == "T" else (0 if key == "P" else 3)
        for w in (self.start, self.stop, self.step):
            w.set_display_decimals(disp)
        is_state = text.strip().upper() in STATE_VARS
        if is_state:
            self.start.setValue(float(DEFAULT_T_RANGE[0]))
            self.stop.setValue(float(DEFAULT_T_RANGE[1]))
            self.step.setValue(float(DEFAULT_T_RANGE[2]))
        else:
            self.start.setValue(float(DEFAULT_X_RANGE[0]))
            self.stop.setValue(float(DEFAULT_X_RANGE[1]))
            self.step.setValue(float(DEFAULT_X_RANGE[2]))

    def target(self) -> str:
        """当前目标；组合框为空时回落到记录的意图。"""
        text = self.var.currentText().strip().upper()
        if text:
            return text
        return self._preferred.strip().upper()

    def as_triple(self) -> tuple:
        return (float(self.start.value()), float(self.stop.value()), float(self.step.value()))

    def set_target(self, target: str) -> None:
        """设置扫描目标，并按目标量纲同步起止值。"""
        self._preferred = target.strip().upper()
        idx = self.var.findText(target, Qt.MatchFlag.MatchFixedString)
        if idx < 0 and self._preferred:
            # 候选项还没填充，先存意图，等 set_candidates 兑现。但默认值与
            # 显示位数仍要按意图生效，否则打开界面（还没载库）时温度行
            # 显示的是成分默认值 0~1，还带 3 位小数
            self._on_target_changed(target)
            return
        if idx >= 0:
            self.var.setCurrentIndex(idx)
        self._on_target_changed(target)

    def set_candidates(self, candidates: Sequence[str]) -> None:
        """替换候选项，尽量保留当前目标。

        注意两个坑：
        1. ``clear()`` 之后必须**先**取回旧目标，否则拿空串去 ``findText`` 只会得 -1；
        2. 旧目标已不在新候选中时要彻底清空（而不是留着不一致的残留），
           否则会出现"组合框空着、target() 却还报着旧元素"的假状态。
        """
        previous = self.target()
        self.var.blockSignals(True)
        self.var.clear()
        self.var.addItems(list(candidates))
        idx = self.var.findText(
            previous,
            Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive,
        )
        if idx < 0:
            idx = self.var.findText(previous)
        if idx >= 0:
            self.var.setCurrentIndex(idx)
        else:
            # 显式置 -1：留 0 会让 Qt 自动选到第一项，等于悄悄改了用户的选择
            self.var.setCurrentIndex(-1)
            self._preferred = ""
        self.var.blockSignals(False)
        current = self.target()
        if current:
            self._on_target_changed(current)


class ConditionPanel(QWidget):
    """条件设置面板。

    Parameters
    ----------
    show_diagram_type
        是否显示"相图类型"分组。高通量扫描不需要它。
    show_plot_options
        是否显示绘图选项。高通量计算不用出图，可隐藏。
    """

    #: 任一输入变化
    changed = pyqtSignal()

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        show_diagram_type: bool = True,
        show_plot_options: bool = True,
    ) -> None:
        super().__init__(parent)
        self._rows: List[SweepRow] = []
        #: 下拉候选，由 :meth:`set_target_candidates` 按数据库刷新
        self._targets: List[str] = []
        self._show_diagram_type = show_diagram_type
        self._show_plot_options = show_plot_options
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ── 相图类型（高通量隐藏） ──────────────────────────────────
        self._type_box = QGroupBox("相图类型", self)
        type_layout = QFormLayout(self._type_box)
        self._diagram = QComboBox(self)
        # 内部键存 itemData，**不能**再靠 currentText() 反查标签：显示文本会被
        # 语言切换翻译，反查失败会静默回落到二元图（比报错更难查）。
        for key, label in DIAGRAM_LABELS.items():
            self._diagram.addItem(label, key)
        self._diagram.setCurrentIndex(0)
        self._diagram.currentIndexChanged.connect(self._on_diagram_changed)
        self._diagram.setToolTip(
            "二元 T–X：1 个组分扫描 + 1 个温度扫描\n"
            "三元等温截面：2 个组分扫描，温度固定\n"
            "Step 图：1 个扫描维度，其余量固定\n"
            "Isopleth：1 个组分扫描 + 1 个温度扫描 + 至少 1 个固定成分"
        )
        type_layout.addRow("类型", self._diagram)
        layout.addWidget(self._type_box)
        self._type_box.setVisible(self._show_diagram_type)

        # ── 扫描维度 ────────────────────────────────────────────────
        sweep_box = QGroupBox("扫描维度", self)
        self._sweep_layout = QVBoxLayout(sweep_box)
        add_btn = QPushButton("+ 添加扫描维度", self)
        # 注意：clicked 信号带一个 bool 参数（是否勾选），直接绑 add_row 会把
        # True 当成 target 传进去，set_target(True).strip() 直接 AttributeError。
        add_btn.clicked.connect(lambda _checked: self.add_row())
        self._sweep_layout.addWidget(add_btn)
        layout.addWidget(sweep_box)

        # ── 固定条件 ────────────────────────────────────────────────
        fixed_box = QGroupBox("固定条件", self)
        fixed_layout = QFormLayout(fixed_box)
        self._pressure = DisplaySpin(0, self)
        self._pressure.setRange(0.0, 1e9)
        self._pressure.setValue(DEFAULT_P)
        self._pressure.setToolTip("标准大气压 101325 Pa")
        self._pressure.setMaximumWidth(120)
        self._fixed_T = DisplaySpin(1, self)
        self._fixed_T.setRange(1.0, 1e5)
        self._fixed_T.setValue(1200.0)
        self._fixed_T.setMaximumWidth(120)
        fixed_layout.addRow("温度 T (K)", self._fixed_T)
        fixed_layout.addRow("压强 P (Pa)", self._pressure)
        # 固定成分（Isopleth / Step 用）：+ 号添加行，每行 [元素][摩尔分数][×]
        self._fixed_comp_rows: List[Dict[str, Any]] = []
        self._fixed_comp_area = QVBoxLayout()
        self._fixed_comp_area.setSpacing(2)
        fixed_comp_btn = QPushButton("+ 添加固定成分", self)
        fixed_comp_btn.clicked.connect(lambda _checked: self.add_fixed_comp_row())
        fixed_layout.addRow("", fixed_comp_btn)
        fixed_layout.addRow(self._fixed_comp_area)
        layout.addWidget(fixed_box)

        # ── 绘图选项（高通量不需要出图，可隐藏） ──────────────────────
        self._opt_box = QGroupBox("绘图选项", self)
        opt_layout = QVBoxLayout(self._opt_box)
        self._opt_tielines = QCheckBox("显示 tie line（两相连线）", self)
        self._opt_tielines.setChecked(True)
        self._opt_tielines.setToolTip("关掉可加快大体系的计算与出图速度")
        self._opt_nodes = QCheckBox("标注三相点节点", self)
        self._opt_fill = QCheckBox("填色相区（官网 shaded 风格：二元 / 三元）", self)
        self._opt_fill.setToolTip(
            "勾选后：二元相图改用 BinaryStrategy 映射并按官网 plot_shaded_binary "
            "填色（单相区淡蓝底、两相区白色、黑色相界、内向刻度）；三元截面按 "
            "plot_shaded_ternary 填色（单相区淡蓝、两相区白色 tie line 多边形、"
            "三相区黄色三角形）。映射未收敛时退回常规绘制"
        )
        opt_layout.addWidget(self._opt_tielines)
        opt_layout.addWidget(self._opt_nodes)
        opt_layout.addWidget(self._opt_fill)
        self._opt_auto = QCheckBox("自动生成映射起点（三元截面）", self)
        self._opt_auto.setToolTip(
            "相区可能不与三角形三条边相连（如 Al-Cu-Y 高温截面），沿边搜索的起点会"
            "一无所获。勾选后先按官方流程生成起点；映射仍为空时自动在三角形内部"
            "补节点重试。仅三元截面有效"
        )
        opt_layout.addWidget(self._opt_auto)
        layout.addWidget(self._opt_box)
        self._opt_box.setVisible(self._show_plot_options)

        layout.addStretch(1)

        # 初始两行：第一行给温度，第二行留给首个组分。此时 _targets 还是空的，
        # 等 configure() 拿到数据库元素后再把第二行的占位补上。
        self.add_row()
        self.add_row()
        self._rows[0].set_target("T")

    # ---------------------------------------------------------------- 数据
    def diagram_type(self) -> str:
        """当前相图类型的内部键（来自 itemData，不受显示语言影响）。"""
        return self._diagram.currentData() or "binary_ztpf"

    def sweeps(self) -> Dict[str, tuple]:
        """返回 {变量: (起点, 终点, 步长)}，忽略维度数为 0 的行。"""
        out: Dict[str, tuple] = {}
        for row in self._rows:
            target = row.target()
            if not target:
                continue
            if target in out:
                continue
            out[target] = row.as_triple()
        return out

    def sweep_lists(self) -> Dict[str, List[float]]:
        """把 (起, 止, 步) 展开成离散采样列表，供高通量逐点求解。"""
        out: Dict[str, List[float]] = {}
        for row in self._rows:
            target = row.target()
            if not target:
                continue
            start, stop, step = row.as_triple()
            if abs(step) < 1e-12:
                continue
            values = []
            cur = start
            # 用整数步数递推，避免浮点累积误差导致末点遗漏
            n = int(round(abs((stop - start) / step)))
            for i in range(n + 1):
                values.append(round(start + (stop - start) * i / max(n, 1), 10))
            if not values:
                continue
            if target in out:
                out[target] = [a + b for a, b in zip(out[target], values)]
            else:
                out[target] = values
        return out

    def fixed(self) -> Dict[str, float]:
        """未被扫描的固定条件（含固定成分）。"""
        swept = set(self.sweeps().keys())
        out: Dict[str, float] = {}
        if "T" not in swept:
            out["T"] = float(self._fixed_T.value())
        if "P" not in swept:
            out["P"] = float(self._pressure.value())
        for row in self._fixed_comp_rows:
            elem = row["combo"].currentText().strip().upper()
            if elem and elem not in swept:
                out[elem] = float(row["spin"].value())
        return out

    def add_fixed_comp_row(self, elem: str = "", value: float = 0.0) -> None:
        """加一行固定成分：[元素下拉][摩尔分数][×]。"""
        row_w = QWidget(self)
        h = QHBoxLayout(row_w)
        h.setContentsMargins(0, 0, 0, 0)
        combo = QComboBox(row_w)
        elems = [t for t in self._targets if t.upper() not in STATE_VARS]
        combo.addItems(elems)
        if elem:
            idx = combo.findText(elem)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        spin = DisplaySpin(3, row_w)
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.01)
        spin.setValue(value)
        spin.setMaximumWidth(104)
        rm = QPushButton("×", row_w)
        rm.setObjectName("iconBtn")
        rm.setFixedWidth(26)
        h.addWidget(combo, 1)
        h.addWidget(spin)
        h.addWidget(rm)
        self._fixed_comp_area.addWidget(row_w)
        entry = {"widget": row_w, "combo": combo, "spin": spin}
        rm.clicked.connect(lambda _checked: self._remove_fixed_comp_row(entry))
        self._fixed_comp_rows.append(entry)

    def _remove_fixed_comp_row(self, entry: Dict[str, Any]) -> None:
        if entry in self._fixed_comp_rows:
            self._fixed_comp_rows.remove(entry)
        entry["widget"].deleteLater()
        self.changed.emit()

    def plot_options(self) -> Dict[str, bool]:
        return {
            "tielines": self._opt_tielines.isChecked(),
            "label_nodes": self._opt_nodes.isChecked(),
            "grid_fill": self._opt_fill.isChecked(),
            "auto_start": self._opt_auto.isChecked(),
        }

    def estimated_points(self) -> int:
        """粗估总采样点数，用于提前提醒用户不要开太大的网格。"""
        sweeps = list(self.sweeps().values())
        if not sweeps:
            return 0
        total = 1
        for start, stop, step in sweeps:
            n = int(abs((stop - start) / step)) + 1 if step else 0
            total *= max(1, n)
        return total

    # ---------------------------------------------------------------- 行管理
    def add_row(self, target: str = "") -> SweepRow:
        row = SweepRow(self._targets, self)
        row.set_target(target)
        row.removed.connect(self._remove_row)
        self._sweep_layout.insertWidget(self._sweep_layout.count() - 1, row)
        self._rows.append(row)
        self.changed.emit()
        return row

    def _remove_row(self, row: SweepRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            row.setParent(None)
            row.deleteLater()
            self.changed.emit()

    def _on_diagram_changed(self, _: int) -> None:
        # 具体维度约束由 ConditionPlan.validate 统一报错并给出修正建议，
        # 这里不擅自替用户改条件——盲改条件比报错更让人困惑。
        self.changed.emit()

    # ---------------------------------------------------------------- 外部更新
    def set_target_candidates(self, elements: Sequence[str]) -> None:
        """按数据库可用元素刷新下拉候选（保留已选中的目标）。

        状态变量只给 ``T``：压强 P 走下方"固定条件"输入框，N（摩尔数）在
        相图计算里没有使用场景，都不作为扫描维度候选（用户明确要求）。
        引擎层面 ConditionPlan 仍支持扫 P/N，只是界面不再列出。
        """
        candidates = [e.upper() for e in elements] + ["T"]
        unchanged = candidates == self._targets
        self._targets = candidates
        # 固定成分行的元素候选同步刷新（保留已选中项）
        comp_candidates = [t for t in candidates if t.upper() not in STATE_VARS]
        for row in self._fixed_comp_rows:
            cur = row["combo"].currentText()
            row["combo"].blockSignals(True)
            row["combo"].clear()
            row["combo"].addItems(comp_candidates)
            idx = row["combo"].findText(cur)
            if idx >= 0:
                row["combo"].setCurrentIndex(idx)
            row["combo"].blockSignals(False)
        if unchanged:
            return
        for row in self._rows:
            row.set_candidates(candidates)
        # 第二行仍是空占位时，用首个可用元素填上，让默认条件开箱即可计算。
        # 只有 T/P/N 可填时**不要**填——那会让"组分扫描"行悄悄变成温度扫描，
        # 用户没选元素却看到两行 T。
        first_comp = next((c for c in self._targets if c not in STATE_VARS), "")
        if first_comp and len(self._rows) > 1 and not self._rows[1].target():
            self._rows[1].set_target(first_comp)

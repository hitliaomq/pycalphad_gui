"""属性曲线页。

计算指定热力学量（G / H / S / Cp）随成分或温度的变化曲线。
走 pycalphad 的 ``Workspace`` 通道——本版本 ``calculate()`` 不接受组分条件
（ARCHITECTURE T6），只有这条路能稳定出图。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.database_manager import LoadedDatabase
from ..core.diagnostics import CalculationError
from ..core.plot_engine import PropertyResult, compute_property_curves
from ..config import (
    PROPERTY_CHOICES,
    PROPERTY_LABELS,
    PROPERTY_SCOPES,
    PROPERTY_SCOPE_LABELS,
)
from ..workers.base_worker import BaseWorker, _Cancelled
from .spinboxes import DisplaySpin
from .. import i18n


def _run_property(
    database: LoadedDatabase,
    comps: List[str],
    phases: List[str],
    target: str,
    x_target: str,
    x_values: List[float],
    options: Dict[str, float],
    figure=None,
    progress=None,
    should_cancel=None,
) -> PropertyResult:
    """见 :func:`_run_diagram` 关于取消语义的说明。"""
    if should_cancel is not None and should_cancel():
        raise _Cancelled()
    return compute_property_curves(
        database, comps, phases, target, x_target, x_values,
        options=options, figure=figure, progress=progress,
    )


class PropertyTab(QWidget):
    """属性曲线页。"""

    status = pyqtSignal(str)
    #: 结果图转交主窗口中央画布（figure, axes, 说明文字）
    figure_ready = pyqtSignal(object, list, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._database: Optional[LoadedDatabase] = None
        self._comps: List[str] = []
        self._phases: List[str] = []
        self._result: Optional[PropertyResult] = None
        self._worker: Optional[BaseWorker] = None
        self._pool = QThreadPool.globalInstance()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        box = QGroupBox("属性设置", self)
        form = QFormLayout(box)

        self._prop = QComboBox(self)
        self._prop.addItems([PROPERTY_LABELS[p] for p in PROPERTY_CHOICES])
        form.addRow("属性", self._prop)

        # 特殊属性（相中元素含量 / 有序度 / 占位分数）需要指明目标相；
        # 相中元素含量还要指元素。平时隐藏，选中对应属性才出现
        self._prop_phase_label = QLabel("目标相")
        self._prop_phase = QComboBox(self)
        form.addRow(self._prop_phase_label, self._prop_phase)
        self._prop_elem_label = QLabel("元素")
        self._prop_elem = QComboBox(self)
        form.addRow(self._prop_elem_label, self._prop_elem)
        self._prop.currentIndexChanged.connect(self._update_prop_fields)
        self._update_prop_fields()

        # T50：默认就是逐相。过去只跑一次全相 Workspace，get() 给的是平衡态
        # 全局值，无论传几个相都只画出一条"平衡相"曲线
        self._scope = QComboBox(self)
        self._scope.addItems([PROPERTY_SCOPE_LABELS[s] for s in PROPERTY_SCOPES])
        self._scope.setToolTip(
            "逐相：每个相单独求解，画的是该相自身的 G/H/S/Cp（含亚稳相）\n"
            "平衡态：只画全局最稳定相的结果\n"
            "两者都画：逐相曲线 + 平衡态虚线参照"
        )
        form.addRow("曲线来源", self._scope)

        self._phase_list = QListWidget(self)
        self._phase_list.setMaximumHeight(92)
        self._phase_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._phase_list.itemChanged.connect(self._on_phase_selection_changed)
        form.addRow("参与逐相计算的相", self._phase_list)
        phase_btns = QHBoxLayout()
        self._btn_all = QPushButton("全选", self)
        self._btn_all.clicked.connect(lambda: self._set_all_phases(True))
        self._btn_none = QPushButton("全不选", self)
        self._btn_none.clicked.connect(lambda: self._set_all_phases(False))
        phase_btns.addWidget(self._btn_all)
        phase_btns.addWidget(self._btn_none)
        phase_btns.addStretch(1)
        form.addRow("", phase_btns)

        self._xvar = QComboBox(self)
        self._xvar.currentTextChanged.connect(self._on_scan_axis_changed)
        form.addRow("扫描轴", self._xvar)

        scan_row = QHBoxLayout()
        self._xstart = DisplaySpin(3, self)
        self._xstart.setDecimals(4)
        self._xstart.setRange(-1e4, 1e4)
        self._xstart.setValue(0.0)
        self._xstop = DisplaySpin(3, self)
        self._xstop.setDecimals(4)
        self._xstop.setRange(-1e4, 1e4)
        self._xstop.setValue(1.0)
        self._xstep = DisplaySpin(3, self)
        self._xstep.setRange(1e-5, 1e3)
        self._xstep.setDecimals(4)
        self._xstep.setValue(0.02)
        for w in (self._xstart, self._xstop, self._xstep):
            scan_row.addWidget(w, 1)  # 等分字段宽度，视觉上齐整
        # T50 附带修复：扫温度时这一行原本还停在组分的 0→1 默认值，
        # 算出来的是 0~1 K 的"温度"——全落空，用户只会看到"没有结果"
        self._scan_unit = QLabel("(摩尔分数)")
        scan_row.addWidget(self._scan_unit, 0)
        # 用固定高度的小部件承载扫描行：把 QHBoxLayout 直接塞进 QFormLayout
        # 时该行会被垂直拉伸成一大块空白、输入框挤在右下角（用户截图反馈）
        scan_host = QWidget(self)
        scan_host.setLayout(scan_row)
        scan_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        form.addRow("起 / 止 / 步长", scan_host)

        self._fixedT = DisplaySpin(1, self)
        self._fixedT.setRange(1.0, 1e5)
        self._fixedT.setValue(600.0)
        form.addRow("固定温度 T (K)", self._fixedT)

        # 扫温度时必须把组分摩尔分数钉死，否则 pycalphad 报"自由度不为零"
        # 固定成分：扫温度时必须把所有剩余组分的摩尔分数钉住（自由度）。
        # 二元体系不加行也行（引擎自动钉第一个组分为 0.5）；三元及以上
        # 逐行添加（如 AL=0.4、CR=0.2），否则计算会报"自由度不为零"
        self._fixed_comp_rows: List[Dict[str, Any]] = []
        self._fixed_comp_candidates: List[str] = []
        self._fixed_comp_area = QVBoxLayout()
        self._fixed_comp_area.setSpacing(2)
        fixed_comp_btn = QPushButton("+ 添加固定成分", self)
        fixed_comp_btn.clicked.connect(lambda _checked: self.add_fixed_comp_row())
        btn_row = QHBoxLayout()
        btn_row.addWidget(fixed_comp_btn)
        btn_row.addStretch(1)
        form.addRow("", btn_row)
        form.addRow(self._fixed_comp_area)
        self._xvar.currentTextChanged.connect(self._on_xvar_changed)

        layout.addWidget(box)

        row = QHBoxLayout()
        self._btn_run = QPushButton("计算属性曲线", self)
        self._btn_run.clicked.connect(self._on_run)
        self._btn_cancel = QPushButton("取消", self)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._progress = QProgressBar(self)
        self._progress.setFormat("%p%")
        row.addWidget(self._btn_run)
        row.addWidget(self._btn_cancel)
        row.addWidget(self._progress, 1)
        layout.addLayout(row)

        # 结果图不再画在这块小画布里，而是发信号给主窗口中央画布
        # （右侧面板只有 ~20% 屏宽，曲线挤在里面没法看——用户反馈）
        self._info = QLabel("尚未计算")
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

        export_row = QHBoxLayout()
        self._btn_export = QPushButton("导出曲线数据…", self)
        self._btn_export.clicked.connect(self._on_export)
        export_row.addWidget(self._btn_export)
        export_row.addStretch(1)
        layout.addLayout(export_row)

        # 末尾必须有 stretch：不然设置分组框是唯一子控件，会被 QVBoxLayout
        # 撑满整页，QFormLayout 再把每一行摊开——控件间距被拉得很大、内容
        # 也不从顶端排（用户反馈）。相图条件页正是靠这个 stretch 才紧凑
        layout.addStretch(1)

    # ---------------------------------------------------------------- 上下文
    def configure(self, database: Optional[LoadedDatabase], elements: List[str],
                  phases: List[str]) -> None:
        self._database = database
        self._phases = list(phases) or (database.phase_names if database else [])
        if database is None:
            self._comps = []
            self._xvar.clear()
            return
        self._comps = database.comps_of(elements)
        phase_items = sorted({str(p) for p in self._phases})
        self._prop_phase.blockSignals(True)
        self._prop_phase.clear()
        self._prop_phase.addItems(phase_items)
        self._prop_phase.blockSignals(False)
        self._prop_elem.blockSignals(True)
        self._prop_elem.clear()
        self._prop_elem.addItems(database.sweep_candidates(elements))
        self._prop_elem.blockSignals(False)
        self._fixed_comp_candidates = database.sweep_candidates(elements)
        for row in self._fixed_comp_rows:
            cur = row["combo"].currentText()
            row["combo"].blockSignals(True)
            row["combo"].clear()
            row["combo"].addItems(self._fixed_comp_candidates)
            idx = row["combo"].findText(cur)
            if idx >= 0:
                row["combo"].setCurrentIndex(idx)
            row["combo"].blockSignals(False)
        # 扫描轴候选只给周期表勾选的元素（T 除外）。这里原先填的是
        # display_elements——20 元素的库里选了 Ti / V，却还能扫 AL，勾选等于
        # 没生效（T52）。
        symbols = ["T"] + database.sweep_candidates(elements)
        previous = self._xvar.currentText().strip().upper()
        self._xvar.blockSignals(True)
        self._xvar.clear()
        self._xvar.addItems(symbols)
        idx = self._xvar.findText(previous, Qt.MatchFlag.MatchFixedString) if previous else -1
        # 旧的扫描轴已不在候选里（比如刚取消勾选该元素）就退回温度，
        # 绝不清空——空着的扫描轴用户根本不知道该填什么
        self._xvar.setCurrentIndex(idx if idx >= 0 else 0)
        self._xvar.blockSignals(False)
        self._on_xvar_changed(self._xvar.currentText())

        self._phase_list.clear()
        for name in self._phases:
            item = QListWidgetItem(str(name))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._phase_list.addItem(item)
        self._on_phase_selection_changed()

    def _on_xvar_changed(self, text: str) -> None:
        """切换扫描轴时，把"起/止/步长"的地盘一起搬过去。

        扫温度 → 需要"固定组分"；扫组分 → 需要"固定温度"。除此之外，这行
        spinbox 的含义也随轴改变（摩尔分数 vs 温度），不跟着换就会出现
        "扫温度却拿 0→1 当温度范围"，算出来一片空（T50）。
        """
        scanning_t = (text or "").strip().upper() == "T"
        self._fixedT.setEnabled(not scanning_t)

        if scanning_t:
            self._scan_unit.setText("(K)")
            for w, rng, val in (
                (self._xstart, (1.0, 1e5), 300.0),
                (self._xstop, (1.0, 1e5), 1500.0),
                (self._xstep, (1e-3, 1e3), 50.0),
            ):
                w.blockSignals(True)
                w.setRange(*rng)
                w.setValue(val)
                w.blockSignals(False)
        else:
            self._scan_unit.setText(i18n.tr("(摩尔分数)"))
            for w, rng, val in (
                (self._xstart, (-1e4, 1e4), 0.0),
                (self._xstop, (-1e4, 1e4), 1.0),
                (self._xstep, (1e-5, 1e3), 0.02),
            ):
                w.blockSignals(True)
                w.setRange(*rng)
                w.setValue(val)
                w.blockSignals(False)

    # ---------------------------------------------------------------- 相选择
    def _checked_phases(self) -> List[str]:
        return [
            self._phase_list.item(i).text()
            for i in range(self._phase_list.count())
            if self._phase_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _on_scan_axis_changed(self, text: str) -> None:
        """扫描轴换成温度时显示 1 位小数，成分保持 3 位（存储精度不变）。"""
        disp = 1 if text.strip().upper() == "T" else 3
        for w in (self._xstart, self._xstop, self._xstep):
            w.set_display_decimals(disp)

    def _set_all_phases(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._phase_list.count()):
            self._phase_list.item(i).setCheckState(state)

    def _on_phase_selection_changed(self) -> None:
        """只有"逐相 / 两者"才需要挑相；纯平衡态算不出相分解。"""
        scope = PROPERTY_SCOPES[self._scope.currentIndex()]
        needs = scope in ("per_phase", "both")
        self._phase_list.setEnabled(needs)
        self._btn_all.setEnabled(needs)
        self._btn_none.setEnabled(needs)

    def _current_scope(self) -> str:
        return PROPERTY_SCOPES[self._scope.currentIndex()]

    def add_fixed_comp_row(self, elem: str = "", value: float = 0.5) -> None:
        """加一行固定成分：[元素下拉][摩尔分数][×]。"""
        row_w = QWidget(self)
        h = QHBoxLayout(row_w)
        h.setContentsMargins(0, 0, 0, 0)
        combo = QComboBox(row_w)
        combo.addItems(self._fixed_comp_candidates)
        if elem:
            idx = combo.findText(elem)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        spin = DisplaySpin(3, row_w)
        spin.setRange(0.0, 1.0)
        spin.setSingleStep(0.01)
        spin.setValue(value)
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

    def _fixed_comps(self) -> Dict[str, float]:
        """用户添加的固定成分（跳过没选元素/重复元素的行）。"""
        out: Dict[str, float] = {}
        for row in self._fixed_comp_rows:
            elem = row["combo"].currentText().strip().upper()
            if elem:
                out[elem] = float(row["spin"].value())
        return out

    def _update_prop_fields(self) -> None:
        """按属性类型显隐"目标相 / 元素"两个下拉。"""
        key = PROPERTY_CHOICES[self._prop.currentIndex()]
        need_phase = key in ("XSEL", "ORDERING", "SITEFRAC")
        need_elem = key == "XSEL"
        self._prop_phase_label.setVisible(need_phase)
        self._prop_phase.setVisible(need_phase)
        self._prop_elem_label.setVisible(need_elem)
        self._prop_elem.setVisible(need_elem)

    def _special_target(self) -> str:
        """把特殊属性 + 目标相(/元素) 拼成引擎认识的属性串。"""
        key = PROPERTY_CHOICES[self._prop.currentIndex()]
        if key == "NP":
            return "NP"
        phase = self._prop_phase.currentText().strip()
        if key == "XSEL":
            elem = self._prop_elem.currentText().strip().upper()
            return f"X({phase}, {elem})"
        if key == "ORDERING":
            return f"degree_of_ordering({phase})"
        if key == "SITEFRAC":
            return f"sitefraction({phase})"
        return key

    # ---------------------------------------------------------------- 计算
    def _on_run(self) -> None:
        if self._database is None or not self._comps:
            self.status.emit("请先在周期表中选择元素")
            return
        target = self._special_target()
        x_target = self._xvar.currentText().strip().upper()
        if not x_target:
            self.status.emit("请选择扫描轴")
            return

        start, stop, step = (
            float(self._xstart.value()),
            float(self._xstop.value()),
            float(self._xstep.value()),
        )
        if step <= 0:
            self.status.emit("步长必须大于 0")
            return
        n = int(abs((stop - start) / step)) + 1
        if n > 5000:
            self.status.emit("采样点过多，请增大步长")
            return
        x_values = [start + i * step for i in range(n)]

        scope = self._current_scope()
        selected = self._checked_phases()
        if scope in ("per_phase", "both") and not selected:
            self.status.emit("请至少勾选一个相（也可先把曲线来源切到「平衡态」）")
            return

        options = {
            "fixed_t": float(self._fixedT.value()),
            "fixed_comps": self._fixed_comps(),
            "curve_scope": scope,
            # 逐相只算勾中的相；纯平衡态不用传，省得引擎白过滤
            **({"per_phase_phases": selected} if scope != "balance" else {}),
        }
        self._worker = BaseWorker(
            _run_property,
            self._database,
            self._comps,
            sorted(self._phases),
            target,
            x_target,
            x_values,
            options,
        )
        self._worker.context = f"属性计算 {target}"
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.succeeded.connect(self._on_success)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.cancelled.connect(self._on_cancelled)

        self._btn_run.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._pool.start(self._worker)

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.emit("正在取消…")

    def _on_progress(self, cur: int, total: int, msg: str) -> None:
        self._progress.setMaximum(max(1, total))
        self._progress.setValue(cur)
        self.status.emit(msg)

    def _on_success(self, result: PropertyResult) -> None:
        self._result = result
        self.figure_ready.emit(
            result.figure, [result.axes],
            i18n.tr(f"✅ {result.title}｜{result.condition_text}"),
        )
        # 引擎最后一报是"正在绘制"，成功收尾要把进度条推满，
        # 否则永远停在 66% 让人以为还卡着
        self._progress.setValue(self._progress.maximum())
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)

        lines = [
            i18n.tr(
                f"✅ {result.title}｜{len(result.series)} 条曲线｜"
                f"{result.condition_text}｜耗时 {result.elapsed_s:.1f} s"
            )
        ]
        # 逐相时被跳过的相必须如实说明，否则用户以为"就是没数据"
        if result.skipped_phases:
            lines.append(
                i18n.tr("⚠ 未出曲线的相：")
                + i18n.tr("、".join(result.skipped_phases))
            )
        if result.scope == "balance":
            lines.append(
                i18n.tr("提示：当前只看平衡态，切到「逐相」可看每个相各自的曲线")
            )
        self._info.setText("\n".join(lines))
        self.status.emit("属性计算完成")

    def _on_failed(self, message: str, detail: str) -> None:
        self._progress.setValue(0)
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._info.setText(i18n.tr(f"❌ {message}\n{detail}"))

    def _on_cancelled(self) -> None:
        self._progress.setValue(0)
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self.status.emit("已取消")

    # ---------------------------------------------------------------- 导出
    def _on_export(self) -> None:
        result = self._result
        if result is None:
            self.status.emit("还没有可导出的数据")
            return
        from .export_dialog import ExportDataTableDialog

        dlg = ExportDataTableDialog(self, default_stem=f"{result.property_name}_curve")
        if dlg.exec() == 1:
            path = dlg.selected_data_path()
            if not path:
                return
            from ..core.exporter import export_series_csv

            try:
                export_series_csv(
                    [(name, xs, ys) for name, (xs, ys) in result.series.items()],
                    path,
                    x_label=result.x_label,
                    y_label=result.y_label,
                )
                self.status.emit(f"已导出 {path}")
            except CalculationError as exc:
                self._info.setText(f"❌ {exc.user_message} — {exc.detail}")

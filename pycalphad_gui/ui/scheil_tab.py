"""Scheil / 平衡凝固页。

封装 `scheil 0.3.0 <https://github.com/PhasesResearchLab/scheil>`_，做两件事：

1. 画「固相分数–温度」曲线（凝固路径），从左到右降温；
2. 顺带给出各相的累计析出曲线，可直接看包晶/共晶反应区间。

scheil 是纯计算库（无 GUI 依赖），但一轮模拟要几十秒到几分钟，
所以像属性页一样丢进线程池，界面只收进度与摘要。

分工与核心层对齐：本文件只做「收集输入 → 起线程 → 收结果」，
具体的条件翻译与失败诊断都在 :mod:`pycalphad_gui.core.scheil_engine`。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.database_manager import LoadedDatabase
from ..core.diagnostics import CalculationError
from ..core.scheil_engine import (
    ScheilConfig,
    ScheilResult,
    guess_liquid_phase,
    run_solidification,
)
from ..config import SCHEIL_METHODS, SCHEIL_METHOD_LABELS
from ..workers.base_worker import BaseWorker, _Cancelled
from .spinboxes import DisplaySpin
from .. import i18n


def _run_scheil(
    config: ScheilConfig,
    figure=None,
    progress=None,
    should_cancel=None,
) -> ScheilResult:
    """见 :func:`_run_diagram` 关于取消语义的说明。"""
    if should_cancel is not None and should_cancel():
        raise _Cancelled()
    return run_solidification(
        config, figure=figure, progress=progress, should_cancel=should_cancel
    )


class ScheilTab(QWidget):
    """Scheil–Gulliver / 平衡凝固模拟页。"""

    #: 状态栏文本
    status = pyqtSignal(str)
    #: 结果图转交主窗口中央画布（figure, axes, 说明文字）
    figure_ready = pyqtSignal(object, list, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._database: Optional[LoadedDatabase] = None
        self._result: Optional[ScheilResult] = None
        self._worker: Optional[BaseWorker] = None
        self._pool = QThreadPool.globalInstance()
        self._comp_widgets: Dict[str, QDoubleSpinBox] = {}
        self._build_ui()

    # ---------------------------------------------------------------- 构建
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ---- 成分 ----
        comp_box = QGroupBox("成分（摩尔分数）", self)
        comp_form = QFormLayout(comp_box)
        self._comp_hint = QLabel("请在左侧周期表中选择元素后载入数据库，这里会自动列出", self)
        self._comp_hint.setWordWrap(True)
        self._comp_hint.setWordWrap(True)
        comp_form.addRow(self._comp_hint)
        self._comp_area = QWidget(comp_box)
        self._comp_layout = QFormLayout(self._comp_area)
        comp_form.addRow("元素", self._comp_area)
        layout.addWidget(comp_box)

        # ---- 模拟参数 ----
        box = QGroupBox("模拟参数", self)
        form = QFormLayout(box)

        self._method = QComboBox(self)
        for key in SCHEIL_METHODS:
            self._method.addItem(SCHEIL_METHOD_LABELS[key], key)
        form.addRow("凝固模型", self._method)

        self._start_t = QDoubleSpinBox(self)
        self._start_t.setRange(1.0, 1e5)
        self._start_t.setDecimals(1)
        self._start_t.setValue(2000.0)
        self._start_t.setToolTip("起始温度，必须落在单一液相区内")
        form.addRow("起始温度 T (K)", self._start_t)

        row = QHBoxLayout()
        self._step_t = QDoubleSpinBox(self)
        self._step_t.setRange(0.5, 500.0)
        self._step_t.setDecimals(1)
        self._step_t.setValue(5.0)
        self._stop = QDoubleSpinBox(self)
        self._stop.setDecimals(5)
        self._stop.setRange(1e-6, 1.0)
        self._stop.setValue(0.0001)
        for w in (self._step_t, self._stop):
            row.addWidget(w)
        form.addRow("温度步长 / 停止条件", row)

        self._liquid = QLineEdit(self)
        self._liquid.setPlaceholderText("留空则自动推断（如 IONIC_LIQ）")
        form.addRow("液相相名", self._liquid)

        self._adaptive = QCheckBox("自适应步长（推荐；关闭时 scheil 0.3.0 会 KeyError）", self)
        self._adaptive.setToolTip(
            i18n.tr("关闭时 scheil 0.3.0 会抛 KeyError，仅用于兼容旧版本")
        )
        self._adaptive.setChecked(True)
        form.addRow("", self._adaptive)
        layout.addWidget(box)

        # ---- 运行 ----
        run_row = QHBoxLayout()
        self._btn_run = QPushButton("开始凝固模拟", self)
        self._btn_run.clicked.connect(self._on_run)
        self._btn_cancel = QPushButton("取消", self)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._progress = QProgressBar(self)
        self._progress.setFormat("%p%")
        run_row.addWidget(self._btn_run)
        run_row.addWidget(self._btn_cancel)
        run_row.addWidget(self._progress, 1)
        layout.addLayout(run_row)

        # 结果图不再画在这块小画布里，而是发信号给主窗口中央画布
        # （右侧面板只有 ~20% 屏宽，曲线挤在里面看不清）

        self._info = QLabel("尚未计算")
        self._info.setWordWrap(True)
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

        export_row = QHBoxLayout()
        self._btn_export = QPushButton("导出模拟结果…", self)
        self._btn_export.clicked.connect(self._on_export)
        self._btn_export.setEnabled(False)
        export_row.addWidget(self._btn_export)
        export_row.addStretch(1)
        layout.addLayout(export_row)
        # 画布移到主窗口后这里没有"撑满"的控件了，末尾补一个 stretch，
        # 否则分组框会被 QVBoxLayout 拉高、控件间距被摊开（必须放在
        # 导出按钮之后，否则按钮会被推到面板底部）
        layout.addStretch(1)

    # ---------------------------------------------------------------- 上下文
    def configure(self, database: Optional[LoadedDatabase], elements: List[str],
                  phases: List[str]) -> None:
        """切库/切元素时重建成分输入区与液相候选。

        这里**只是重新建控件**，不跑计算——启动一次凝固模拟要好几十秒，
        切元素时不该被牵连。
        """
        self._database = database
        # 换库可能只换了元素符号（典型：ESPEI 产出的 TDB），
        # 原来填过的摩尔分数能保留就保留，别让用户重填一遍
        previous = {
            symbol: spin.value() for symbol, spin in self._comp_widgets.items()
        }
        self._result = None
        self._btn_export.setEnabled(False)
        self._info.setText(i18n.tr("尚未计算"))
        # 画布已移到主窗口中央，这里只需清掉上一份结果引用

        # 清掉上一轮的元素行
        while self._comp_layout.count() > 0:
            item = self._comp_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._comp_widgets = {}

        if database is None:
            self._comp_hint.setText(i18n.tr("请先在周期表中选择元素并导入数据库"))
            return

        # 组分行只给周期表勾选的元素。原先铺的是 display_elements——20 元素的
        # 库里一进页面就摆 20 个输入框，只有勾了的那几个才该有值（T52）。
        symbols = database.sweep_candidates(elements)
        self._comp_hint.setText(i18n.tr(
            f"体系：{database.name}｜{' + '.join(symbols) if symbols else '未选元素'}"
            f"｜库内共 {len(database.display_elements)} 个元素，只有勾选的会出现下方。"
            "摩尔分数之和不必恰好为 1，剩余部分由空位（VA）补齐；"
            "最后一个填入的元素会被当作溶剂（scheil 只接受独立组分）。"
        ))
        if not symbols:
            self._comp_widgets = {}
            return

        for symbol in symbols:
            spin = DisplaySpin(3, self._comp_area)
            spin.setRange(0.0, 1.0)
            spin.setDecimals(4)
            spin.setToolTip(i18n.tr(f"{symbol} 的摩尔分数"))
            self._comp_layout.addRow(symbol, spin)
            self._comp_widgets[symbol] = spin

        # 只有"一个值都还没填"时才给末尾元素送 0.7：往一个已经填了成分的
        # 体系里再加元素时，默认 0.7 会把摩尔分数总和顶到 1 以上
        blank = not any(v > 0 for v in previous.values())
        for symbol in symbols:
            spin = self._comp_widgets.get(symbol)
            if spin is None:
                continue
            if symbol in previous and previous[symbol] > 0:
                spin.setValue(previous[symbol])
            else:
                spin.setValue(0.7 if (blank and symbol == symbols[-1]) else 0.0)

        # 液相候选：优先自动推断的结果，用户可手动改
        self._liquid.setText(guess_liquid_phase(database, list(phases) or list(database.phase_names)))

    def _collect_composition(self) -> Dict[str, float]:
        """只收摩尔分数 > 0 的元素。"""
        return {
            symbol: float(spin.value())
            for symbol, spin in self._comp_widgets.items()
            if spin.value() > 0
        }

    # ---------------------------------------------------------------- 运行
    def _on_run(self) -> None:
        database = self._database
        if database is None:
            self.status.emit("请先在周期表中选择元素")
            return
        composition = self._collect_composition()
        if not composition:
            self._info.setText(i18n.tr("⚠ 请至少填写一个元素的摩尔分数"))
            self.status.emit("请填写成分")
            return

        phases = list(database.phase_names)
        config = ScheilConfig(
            database=database,
            comps=database.comps_of(list(composition.keys())),
            phases=phases,
            composition=composition,
            start_temperature=float(self._start_t.value()),
            step_temperature=float(self._step_t.value()),
            stop=float(self._stop.value()),
            adaptive=self._adaptive.isChecked(),
            method=self._method.currentData() or "scheil",
            liquid_phase_name=self._liquid.text().strip(),
        )

        self._result = None
        self._btn_export.setEnabled(False)
        self._btn_run.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._progress.setValue(0)
        self._worker = BaseWorker(_run_scheil, config)
        self._worker.context = "Scheil 凝固模拟"
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.succeeded.connect(self._on_success)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.cancelled.connect(self._on_cancelled)
        self._pool.start(self._worker)

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.emit("正在取消…")

    def _on_progress(self, cur: int, total: int, msg: str) -> None:
        self._progress.setMaximum(max(1, total))
        self._progress.setValue(cur)
        if msg:
            self.status.emit(msg)

    def _on_success(self, result: ScheilResult) -> None:
        self._result = result
        self.figure_ready.emit(
            result.figure, result.axes_list(),
            i18n.tr(f"✅ Scheil 凝固曲线（{self._method.currentText()}）"),
        )
        # 引擎最后一报是 3/4，成功收尾必须推满，否则永远停在 75%
        self._progress.setValue(self._progress.maximum())
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._btn_export.setEnabled(True)
        self._info.setText(self._describe(result))
        self.status.emit(
            f"{'Scheil' if result.method == 'scheil' else '平衡'}凝固模拟完成，"
            f"{len(result.frame)} 个温度步，耗时 {result.elapsed_s:.1f} s"
        )

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

    # ---------------------------------------------------------------- 展示
    def _describe(self, result: ScheilResult) -> str:
        summary: Dict[str, Any] = result.summary
        end_t = summary.get("终点温度 (K)")
        parts = [
            i18n.tr(f"✅ {SCHEIL_METHOD_LABELS.get(result.method, result.method)}"),
            i18n.tr(f"{len(result.frame)} 个温度步"),
            i18n.tr(f"终点 {float(end_t):.1f} K") if end_t is not None else "",
            i18n.tr(f"耗时 {result.elapsed_s:.1f} s"),
        ]
        # 收敛信息以摘要为准：引擎把"固相分数已到 1"也算作跑完，
        # 直接用 result.converged 会误报失败
        if str(summary.get("是否收敛", "")).startswith("否"):
            parts.append(i18n.tr("⚠ 模拟未走完（可加大步长或提高起始温度）"))
        return "｜".join(p for p in parts if p)

    # ---------------------------------------------------------------- 导出
    def _on_export(self) -> None:
        result = self._result
        if result is None or result.frame is None or getattr(result.frame, "empty", True):
            self.status.emit("没有可导出的结果")
            return
        from .export_dialog import ExportDataTableDialog

        dlg = ExportDataTableDialog(self, default_stem="scheil_solidification")
        if dlg.exec() == 1:
            path = dlg.selected_data_path()
            if not path:
                return
            from ..core.exporter import export_dataframe, export_figure

            figure_path = None
            try:
                export_dataframe(result.frame, path)
                # 表格后缀可能是 .xlsx/.csv，图片另存一份同名同目录
                figure_path = export_figure(
                    result.figure,
                    str(path).rsplit(".", 1)[0] + ".png",
                )
                self.status.emit(f"已导出 {path}" + (f"、{figure_path}" if figure_path else ""))
            except CalculationError as exc:
                self._info.setText(i18n.tr(f"❌ {exc.user_message} — {exc.detail}"))

    def export_figure_only(self, path: str) -> Any:
        """供主窗口「导出当前图片」复用；返回导出的路径。"""
        from ..core.exporter import export_figure

        if self._result is None:
            raise CalculationError("没有可导出的图", "请先运行一次凝固模拟")
        return export_figure(self._result.figure, path)

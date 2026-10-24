"""相图的「条件 + 计算」面板（右侧停靠页的第一页）。

这里只负责把条件面板的值交给后台线程算完，再把结果交给中央画布去显示。
计算与显示分开，好处是：面板在 dock 里被折叠了，图照样能看。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.conditions import ConditionPlan
from ..core.database_manager import LoadedDatabase
from ..core.diagnostics import CalculationError
from ..core.plot_engine import PlotResult, compute_diagram
from ..workers.base_worker import BaseWorker, _Cancelled
from .condition_panel import ConditionPanel
from .. import i18n


def _run_diagram(
    database: LoadedDatabase,
    comps: List[str],
    phases: List[str],
    plan: ConditionPlan,
    options: Dict[str, Any],
    figure,
    progress=None,
    should_cancel=None,
) -> PlotResult:
    """线程执行体：把参数交给引擎，返回统一的结果对象。

    pycalphad 内部没有中断点，长计算无法被抢占式终止；这里只保证
    「启动前已取消」能被立刻响应，运行中的取消将在当前批次结束后生效。
    """
    if should_cancel is not None and should_cancel():
        raise _Cancelled()
    return compute_diagram(
        database, comps, phases, plan, options, figure=figure, progress=progress
    )


class DiagramPanel(QWidget):
    """相图条件与计算控制。"""

    #: 状态栏文本
    status = pyqtSignal(str)
    #: 算完的图，交给中央画布
    result_ready = pyqtSignal(object)
    #: 前端异常（参数不合法等），供画布下方提示区显示
    notice = pyqtSignal(str, str)
    #: 计算中/结束，供主工具栏联动"取消"按钮
    busy_changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._database: Optional[LoadedDatabase] = None
        self._comps: List[str] = []
        self._phases: List[str] = []
        self._worker: Optional[BaseWorker] = None
        self._pool = QThreadPool.globalInstance()
        self._build_ui()

    # ---------------------------------------------------------------- 界面
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._panel = ConditionPanel(self)
        self._panel.changed.connect(self._on_plan_changed)
        layout.addWidget(self._panel, 1)

        row = QHBoxLayout()
        self._btn_draw = QPushButton("计算并绘制", self)
        self._btn_draw.setObjectName("primary")
        self._btn_draw.clicked.connect(self.on_draw)
        self._btn_cancel = QPushButton("取消", self)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self.on_cancel)
        row.addWidget(self._btn_draw)
        row.addWidget(self._btn_cancel)
        row.addStretch(1)
        layout.addLayout(row)

        self._progress = QProgressBar(self)
        self._progress.setFormat("%p%  %v/%m")
        self._progress.setTextVisible(True)
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._info = QLabel("设定好扫描条件后点「计算并绘制」")
        self._info.setWordWrap(True)
        self._info.setWordWrap(True)
        self._info.setStyleSheet("color: #7a8494;")
        layout.addWidget(self._info)

        # Step 图的 y 轴内容（仅类型 = Step 图时可见）：
        # 相分数（默认）/ 相中元素含量 / 任意属性量（GM、CPM、HM…）
        step_row = QGridLayout()
        step_row.setContentsMargins(0, 0, 0, 0)
        step_row.addWidget(QLabel("Y 轴"), 0, 0)
        self._step_y_mode = QComboBox(self)
        self._step_y_mode.addItems(["相分数", "相中元素含量", "属性量"])
        step_row.addWidget(self._step_y_mode, 0, 1)
        self._step_y_elem = QComboBox(self)
        step_row.addWidget(self._step_y_elem, 0, 2)
        self._step_y_prop = QLineEdit(self)
        self._step_y_prop.setPlaceholderText("如 CPM / HM / SM")
        self._step_y_prop.setText("CPM")
        step_row.addWidget(self._step_y_prop, 0, 3)
        self._step_y_host = QWidget(self)
        self._step_y_host.setLayout(step_row)
        self._step_y_host.setVisible(False)
        layout.addWidget(self._step_y_host)
        self._step_y_mode.currentIndexChanged.connect(
            lambda _i: self._update_step_y_row()
        )
        layout.addStretch(0)

    def set_enabled(self, enabled: bool) -> None:
        """未载入数据库时禁用本页，避免点了没反应。"""
        self._btn_draw.setEnabled(enabled)

    # ---------------------------------------------------------------- 上下文
    def configure(self, database: Optional[LoadedDatabase], elements: List[str],
                  phases: List[str]) -> None:
        """数据库或选择变化后刷新本页可用项。"""
        self._database = database
        self._phases = list(phases) or (database.phase_names if database else [])
        if database is not None:
            # 候选只给周期表勾选的元素：多元素库（如 cost507R 有 20 个）若把
            # 库内全部元素都塞进下拉，勾选就形同虚设（T52）。
            # sweep_candidates 顺带滤掉库外符号与空位，别让脏符号进下拉
            self._panel.set_target_candidates(database.sweep_candidates(elements))
            self._comps = database.comps_of(elements)
            # Step 图"相中元素含量"的元素候选与扫描轴同源
            prev_elem = self._step_y_elem.currentText()
            self._step_y_elem.blockSignals(True)
            self._step_y_elem.clear()
            self._step_y_elem.addItems(database.sweep_candidates(elements))
            if prev_elem:
                idx = self._step_y_elem.findText(prev_elem)
                if idx >= 0:
                    self._step_y_elem.setCurrentIndex(idx)
            self._step_y_elem.blockSignals(False)
            if self._comps:
                self.status.emit(f"计算组分：{', '.join(self._comps)}")
        else:
            self._comps = []

    # ------------------------------------------------- 对内嵌面板的透传
    def sweeps(self) -> Any:
        """当前扫描条件（供外部读取 / 测试断言）。"""
        return self._panel.sweeps()

    def fixed(self) -> Any:
        """当前固定条件。"""
        return self._panel.fixed()

    def plot_options(self) -> Any:
        """当前绘图选项（含 Step 图 y 轴选择）。"""
        opts = dict(self._panel.plot_options())
        opts.update(self._step_y_options())
        return opts

    def _update_step_y_row(self) -> None:
        """按当前相图类型与 y 轴选择显隐 Step 行的子控件。"""
        is_step = self._panel.diagram_type() == "step"
        self._step_y_host.setVisible(is_step)
        if not is_step:
            return
        mode = self._step_y_mode.currentIndex()
        self._step_y_elem.setVisible(mode == 1)
        self._step_y_prop.setVisible(mode == 2)

    def _step_y_options(self) -> Dict[str, Any]:
        """Step 图 y 轴选项；非 Step 类型返回空字典。"""
        if self._panel.diagram_type() != "step":
            return {}
        mode = self._step_y_mode.currentIndex()
        if mode == 1:
            elem = self._step_y_elem.currentText().strip().upper()
            return {"step_y": ("x", elem)} if elem else {}
        if mode == 2:
            prop = self._step_y_prop.text().strip()
            return {"step_y": ("prop", prop)} if prop else {}
        return {}

    def _on_plan_changed(self) -> None:
        self._update_step_y_row()
        n = self._panel.estimated_points()
        if n > 5000:
            self._info.setText(i18n.tr(f"⚠ 当前扫描网格约 {n:,} 点，计算可能非常缓慢"))
        else:
            self._info.setText(i18n.tr("设定好扫描条件后点「计算并绘制」"))

    # ---------------------------------------------------------------- 计算
    def on_draw(self) -> None:
        if self._database is None:
            self.status.emit("请先加载数据库")
            return
        if not self._comps:
            self.status.emit("请先在周期表中选择元素")
            return

        try:
            plan = ConditionPlan.from_ui(
                self._database,
                self._panel.diagram_type(),
                self._panel.sweeps(),
                self._panel.fixed(),
            )
        except CalculationError as exc:
            self._info.setText(f"⚠ {exc.user_message}\n{exc.detail}")
            self.status.emit(exc.user_message)
            self.notice.emit(exc.user_message, exc.detail)
            return

        self._worker = BaseWorker(
            _run_diagram,
            self._database,
            self._comps,
            sorted(self._phases),
            plan,
            # 必须走外层合并：这里曾有一步直接取内层条件面板的 plot_options，
            # 把 Step 图的 y 轴选择整个丢了（改 y 后出的图仍是相分数）
            self.plot_options(),
            None,  # figure：由引擎在子线程内创建，UI 层再包装成控件
        )
        self._worker.context = "绘制相图"
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.succeeded.connect(self._on_success)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.cancelled.connect(self._on_cancelled)

        self._btn_draw.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._progress.setValue(0)
        self.busy_changed.emit(True)
        self._pool.start(self._worker)

    def on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.emit("正在取消…")

    def _on_progress(self, cur: int, total: int, msg: str) -> None:
        self._progress.setMaximum(max(1, total))
        self._progress.setValue(cur)
        self.status.emit(msg)

    def _on_success(self, result: PlotResult) -> None:
        self._result = result
        self.result_ready.emit(result)
        self._btn_draw.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._progress.setValue(self._progress.maximum())
        self._info.setText(i18n.tr(
            f"✅ {result.title}\n条件：{result.condition_text}"
            f"\n耗时 {result.elapsed_s:.1f} s"
        ))
        self.busy_changed.emit(False)
        self.status.emit("绘制完成")

    def _on_failed(self, message: str, detail: str) -> None:
        self._btn_draw.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._info.setText(f"❌ {message}\n{detail}")
        self.notice.emit(message, detail)
        self.busy_changed.emit(False)
        self.status.emit("计算失败")

    def _on_cancelled(self) -> None:
        self._btn_draw.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self.busy_changed.emit(False)
        self.status.emit("已取消")
        self._info.setText(i18n.tr("已取消计算"))


__all__ = ["DiagramPanel"]

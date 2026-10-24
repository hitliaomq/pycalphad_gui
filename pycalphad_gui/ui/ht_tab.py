"""高通量计算页。

对条件空间做笛卡尔展开，逐点求解平衡态并汇总成表格。
并行默认走线程池（Database 可安全共享、取消简单）；
可选进程池以获得真正的 CPU 并行（Database 实测可 pickle）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.database_manager import LoadedDatabase
from ..core.diagnostics import CalculationError
from ..core.high_throughput import HTConfig, HTResult, run_high_throughput
from ..config import HT_OUTPUTS, HT_OUTPUT_LABELS
from ..workers.base_worker import BaseWorker
from .condition_panel import ConditionPanel
from .. import i18n


def _run_ht(config: HTConfig, progress=None, should_cancel=None) -> HTResult:
    return run_high_throughput(config, progress=progress, should_cancel=should_cancel)


def _cell_text(value: Any) -> str:
    """表格单元格文本。

    只放行"有实际含义"的值：``None``（含 core 层转过来的 NaN/inf）显示为
    空串，其余一律 ``str()``。这里比原来的 ``isinstance(..., (int, float,
    str))`` 更稳——后者会把 ``np.int64`` 这类 numpy 标量误判为不可显示。
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):  # pandas 的 NaN / NaT，标量安全，数组才返回序列
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


class HighThroughputTab(QWidget):
    """高通量页。"""

    status = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._database: Optional[LoadedDatabase] = None
        self._comps: List[str] = []
        self._phases: List[str] = []
        self._result: Optional[HTResult] = None
        self._worker: Optional[BaseWorker] = None
        self._pool = QThreadPool.globalInstance()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._panel = ConditionPanel(self, show_diagram_type=False, show_plot_options=False)
        self._panel.changed.connect(self._on_plan_changed)
        layout.addWidget(self._panel)

        opts = QGroupBox("任务设置", self)
        # 横排一行的最小宽度 = 所有复选框相加（英文下 1700px+），拆成 3 列网格
        form = QGridLayout(opts)
        form.setHorizontalSpacing(12)

        self._outputs: Dict[str, QCheckBox] = {}
        for i, key in enumerate(HT_OUTPUTS):
            cb = QCheckBox(HT_OUTPUT_LABELS.get(key, key), self)
            cb.setChecked(key in ("stable_phases", "gm_min", "n_phases"))
            self._outputs[key] = cb
            form.addWidget(cb, i // 3, i % 3)

        layout.addWidget(opts)

        run_row = QHBoxLayout()
        self._parallel = QSpinBox(self)
        self._parallel.setRange(1, 32)
        self._parallel.setValue(4)
        self._parallel.setToolTip("并发计算线程数（选择进程池时即进程数）")
        self._mode = QComboBox(self)
        self._mode.addItems(["线程池（推荐）", "进程池（CPU 密集）"])
        self._mode.setToolTip(
            "线程池：Database 共享内存、取消及时\n进程池：规避 GIL，启动开销较大"
        )
        self._btn_run = QPushButton("开始高通量扫描", self)
        self._btn_run.clicked.connect(self._on_run)
        self._btn_cancel = QPushButton("取消", self)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._on_cancel)

        # 一行塞"并发+模式+两个按钮"的最小宽 = 各项相加（英文下 530px+），
        # 是高通量页撑宽面板的元凶——拆成两行，最宽的就只剩"并发+模式"
        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel("并发"), 0)
        opts_row.addWidget(self._parallel)
        opts_row.addWidget(QLabel("模式"), 0)
        opts_row.addWidget(self._mode, 1)
        layout.addLayout(opts_row)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_run)
        btn_row.addWidget(self._btn_cancel)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self._progress = QLabel("就绪", self)
        self._progress.setWordWrap(True)
        layout.addWidget(self._progress)

        self._table = QTableWidget(self)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self._table, 1)

        export_row = QHBoxLayout()
        self._btn_export = QPushButton("导出结果…", self)
        self._btn_export.clicked.connect(self._on_export)
        export_row.addWidget(self._btn_export)
        export_row.addStretch(1)
        layout.addLayout(export_row)

    # ---------------------------------------------------------------- 上下文
    def configure(self, database: Optional[LoadedDatabase], elements: List[str],
                  phases: List[str]) -> None:
        self._database = database
        self._phases = list(phases) or (database.phase_names if database else [])
        if database is not None:
            self._comps = database.comps_of(elements)
            self._panel.set_target_candidates(database.sweep_candidates(elements))
        else:
            self._comps = []

    # ---------------------------------------------------------------- 计算
    def _on_plan_changed(self) -> None:
        sweeps = self._panel.sweep_lists()
        total = 1
        for values in sweeps.values():
            total *= len(values)
        if total > 20000:
            self._progress.setText(
                i18n.tr(f"⚠ 预计 {total:,} 个计算点，耗时可能很长")
            )

    def _on_run(self) -> None:
        if self._database is None or not self._comps:
            self.status.emit("请先在周期表中选择元素")
            return

        sweeps = self._panel.sweep_lists()
        if not sweeps:
            self.status.emit("请至少设置一个扫描维度")
            return

        outputs = [k for k, cb in self._outputs.items() if cb.isChecked()]
        if not outputs:
            self.status.emit("请至少选择一个输出指标")
            return

        fixed = self._panel.fixed()
        # 高通量要求所有维度都是离散点，未被扫描的条件按固定值处理
        if "T" not in sweeps and "T" not in fixed:
            fixed["T"] = 1200.0

        try:
            config = HTConfig(
                database=self._database,
                comps=self._comps,
                phases=sorted(self._phases),
                sweeps=sweeps,
                outputs=outputs,
                parallel=int(self._parallel.value()),
                use_process_pool=(self._mode.currentIndex() == 1),
            )
        except CalculationError as exc:
            self._progress.setText(i18n.tr(f"⚠ {exc.user_message} — {exc.detail}"))
            return

        self._worker = BaseWorker(_run_ht, config)
        self._worker.context = "高通量扫描"
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.succeeded.connect(self._on_success)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.cancelled.connect(self._on_cancelled)

        self._btn_run.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._table.setRowCount(0)
        self._pool.start(self._worker)
        self._progress.setText(i18n.tr(f"正在计算 {config.total_points} 个点…"))

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._progress.setText(i18n.tr("正在取消…"))

    def _on_progress(self, cur: int, total: int, msg: str) -> None:
        self._progress.setText(i18n.tr(f"{msg}（{total}）"))

    def _on_success(self, result: HTResult) -> None:
        self._result = result
        self._fill_table(result)
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        tail = i18n.tr(f"，{result.n_failed} 个失败") if result.n_failed else ""
        tail += i18n.tr("（已取消）") if result.cancelled else ""
        self._progress.setText(i18n.tr(
            f"✅ 完成 {result.n_ok}/{result.n_total} 点，耗时 {result.elapsed_s:.1f} s{tail}"
        ))
        self.status.emit("高通量扫描完成")

    def _on_failed(self, message: str, detail: str) -> None:
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._progress.setText(f"❌ {message} — {detail}")

    def _on_cancelled(self) -> None:
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._progress.setText(i18n.tr("已取消"))

    def _fill_table(self, result: HTResult) -> None:
        frame = result.frame
        self._table.setColumnCount(len(frame.columns))
        # 表头只翻**显示**：DataFrame 里的列名（也是导出 CSV 的表头）保持原样，
        # 不然用户拿到的数据文件跟文档对不上
        self._table.setHorizontalHeaderLabels(
            [i18n.tr(str(c)) for c in frame.columns]
        )
        self._table.setRowCount(len(frame))
        for r in range(len(frame)):
            for c, col in enumerate(frame.columns):
                # 不能写成 isinstance(value, (int, float, str))：
                # DataFrame.iat 读回来的是 np.int64，而 np.int64 不是 Python int
                # 的子类，整个人被判成"不可显示" → "共存相数"整列空白（T49）
                self._table.setItem(r, c, QTableWidgetItem(_cell_text(frame.iat[r, c])))

    # ---------------------------------------------------------------- 导出
    def _on_export(self) -> None:
        result = self._result
        if result is None or result.frame.empty:
            self.status.emit("没有可导出的结果")
            return
        from .export_dialog import ExportDataTableDialog

        dlg = ExportDataTableDialog(self, default_stem="high_throughput")
        if dlg.exec() == 1:
            path = dlg.selected_data_path()
            if not path:
                return
            from ..core.exporter import export_dataframe

            try:
                export_dataframe(result.frame, path)
                for point, reason in result.failures[:5]:
                    self.status.emit(f"失败点 {point}：{reason}")
                self.status.emit(f"已导出 {path}")
            except CalculationError as exc:
                self._progress.setText(i18n.tr(f"❌ {exc.user_message} — {exc.detail}"))

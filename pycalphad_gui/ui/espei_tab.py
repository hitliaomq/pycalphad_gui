"""ESPEI 参数优化页。

把 ESPEI 的三种玩法（生成参数 / MCMC 拟合 / 校验数据集）做成同一个面板的三个模式。
ESPEI 一轮训练动辄几分钟到几小时，全部丢进线程池，界面只负责收进度与日志。

产出的 TDB 可以一键「载入到主窗口」，直接接着算相图或做凝固模拟——
这条回路是本页最大的实用价值：数据集 → 参数 → 相图。
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QThreadPool, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.database_manager import LoadedDatabase
from ..config import DEFAULT_OUTPUT_DB
from ..core.espei_engine import (
    EspeiResult,
    EspeiSettings,
    list_datasets,
    parse_aicc_penalty,
    parse_tags,
    run_espei,
)
from ..core.diagnostics import CalculationError
from ..config import (
    ESPEI_DATA_WEIGHTS,
    ESPEI_EXCESS_MODELS,
    ESPEI_MODE_LABELS,
    ESPEI_MODES,
    ESPEI_PRIORS,
    ESPEI_REF_STATES,
)
from ..workers.base_worker import BaseWorker
from .theme import icon
from .. import i18n


def _run_espei(
    settings: EspeiSettings,
    progress: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> EspeiResult:
    """见 PropertyTab._run_*：取消语义由 BaseWorker 保证。"""
    return run_espei(settings, progress=progress, should_cancel=should_cancel, log=log)


def _parse_data_weights(text: str) -> Dict[str, float]:
    """解析 ``"ZPF=1.0, ACR=0.5"`` 形式的数据权重串。

    解析失败给出明确提示，而不是把异常丢给 ESPEI 去报（那时已经等了很久）。
    """
    text = (text or "").strip()
    if not text:
        return {}
    weights: Dict[str, float] = {}
    for chunk in text.replace("；", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise CalculationError(
                f"数据权重 {chunk!r} 格式不正确",
                "应写成「ZPF=1.0, ACR=0.5」这种「键=数值」的形式，"
                f"可用键：{', '.join(ESPEI_DATA_WEIGHTS)}",
            )
        key, _, value = chunk.partition("=")
        key = key.strip().upper()
        if key not in ESPEI_DATA_WEIGHTS:
            raise CalculationError(
                f"数据权重里的 {key!r} 不是合法键",
                f"可用键：{', '.join(ESPEI_DATA_WEIGHTS)}",
            )
        try:
            weights[key] = float(value)
        except ValueError as exc:
            raise CalculationError(
                f"数据权重 {key} 的值 {value!r} 不是数字",
                "例如 ZPF=1.0、HM=0.5",
            ) from exc
    return weights


class EspeiTab(QWidget):
    """ESPEI 参数优化页。"""

    #: 状态栏文本
    status = pyqtSignal(str)
    #: ESPEI 产出了 TDB，主窗口据此把它载入为当前数据库
    database_ready = pyqtSignal(str)
    #: 拟合对比图转交主窗口中央画布（figure, axes, 说明文字）
    figure_ready = pyqtSignal(object, list, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._database: Optional[LoadedDatabase] = None
        self._result: Optional[EspeiResult] = None
        self._worker: Optional[BaseWorker] = None
        self._pool = QThreadPool.globalInstance()
        self._build_ui()

    # ---------------------------------------------------------------- 构建
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        mode_box = QGroupBox("运行模式", self)
        mode_form = QFormLayout(mode_box)
        self._mode = QComboBox(self)
        self._mode.addItems([ESPEI_MODE_LABELS[m] for m in ESPEI_MODES])
        self._mode.setToolTip(
            "生成参数：线性回归直接出一套 TDB（快）\n"
            "MCMC 拟合：贝叶斯采样，需要已有的参数库（慢）\n"
            "校验数据集：只检查数据集，不训练"
        )
        mode_form.addRow("模式", self._mode)
        layout.addWidget(mode_box)

        io_box = QGroupBox("输入与输出", self)
        io_form = QFormLayout(io_box)

        # 这三个必须**先创建**再交给 _path_row：它只负责排版，不负责造控件
        self._datasets = QLineEdit(self)
        self._datasets.setToolTip("ESPEI 在这里递归搜索 *.json 数据集")
        self._phase_models = QLineEdit(self)
        self._phase_models.setToolTip("描述 CALPHAD 相模型的 JSON，顶层须含 components 与 phases")
        self._output_db = QLineEdit(DEFAULT_OUTPUT_DB, self)
        self._output_db.setToolTip("ESPEI 写出的 TDB 路径")

        io_form.addRow(self._path_row("数据集目录", self._datasets, "目录", self._browse_datasets))
        io_form.addRow(self._path_row("phase_models", self._phase_models, "文件", self._browse_phase_models))
        io_form.addRow(self._path_row("输出 TDB", self._output_db, "文件", self._browse_output))

        self._input_db = QLineEdit(self)
        self._input_db.setPlaceholderText("MCMC 模式下的起始数据库；留空则只做 generate")
        self._input_db_browse = QPushButton(icon("open"), "…", self)
        self._input_db_browse.setFixedWidth(28)
        self._input_db_browse.setToolTip("选择起始 TDB")
        self._input_db_browse.clicked.connect(self._browse_input_db)
        io_form.addRow(self._path_row("起始数据库", self._input_db, "文件", None, browse_btn=self._input_db_browse))

        self._ref_state = QComboBox(self)
        self._ref_state.addItems(ESPEI_REF_STATES)
        io_form.addRow("参考态", self._ref_state)

        self._excess = QComboBox(self)
        self._excess.addItems(ESPEI_EXCESS_MODELS)
        self._excess.setToolTip("ESPEI 目前只支持 linear（线性超额自由能）")
        io_form.addRow("超额模型", self._excess)

        self._ridge = QDoubleSpinBox(self)
        self._ridge.setRange(0.0, 1e6)
        self._ridge.setDecimals(4)
        self._ridge.setValue(0.0)
        self._ridge.setSpecialValueText(i18n.tr("关闭（普通最小二乘）"))
        self._ridge.setToolTip("岭回归系数；留 0 表示不做正则化")
        io_form.addRow("岭回归 α", self._ridge)

        self._tags = QLineEdit(self)
        self._tags.setPlaceholderText(
            "可选：dft:-idmix,-mag;estimated-entropy:-idmix,-mag,weight=0.1"
        )
        self._tags.setToolTip(
            "对应 ESPEI 的 system.tags：给带指定标签的数据集追加排除项或权重。\n"
            "留空表示不启用。也接受 JSON 对象或 .json / .yaml 文件路径。"
        )
        io_form.addRow("数据集标签", self._tags)

        self._aicc = QLineEdit(self)
        self._aicc.setPlaceholderText("可选：LIQUID:HM=1.4,LIQUID:SM=1.4")
        self._aicc.setToolTip(
            "对应 generate_parameters.aicc_penalty_factor：按相覆盖 AICc 惩罚倍数；"
            "留空表示使用 ESPEI 默认值。"
        )
        io_form.addRow("AICc 惩罚", self._aicc)

        layout.addWidget(io_box)

        mcmc_box = QGroupBox("MCMC 设置", self)
        mcmc_form = QFormLayout(mcmc_box)
        self._iterations = QSpinBox(self)
        self._iterations.setRange(1, 1000000)
        self._iterations.setValue(100)
        mcmc_form.addRow("迭代次数", self._iterations)

        self._cores = QSpinBox(self)
        self._cores.setRange(1, 64)
        self._cores.setValue(1)
        mcmc_form.addRow("并行进程数", self._cores)

        self._scheduler = QComboBox(self)
        self._scheduler.addItem("单核串行", "none")
        self._scheduler.addItem("dask 并行", "dask")
        self._scheduler.setToolTip(
            "单核串行与官方教程的 scheduler: null 一致；"
            "dask 会启动后台工作进程（仅在使用多核时有优势）。"
        )
        mcmc_form.addRow("运行调度", self._scheduler)

        self._chains = QSpinBox(self)
        self._chains.setRange(2, 10000)
        self._chains.setSingleStep(2)
        self._chains.setValue(2)
        mcmc_form.addRow("每条链 walker 数（偶数）", self._chains)

        self._jitter = QDoubleSpinBox(self)
        self._jitter.setRange(0.0, 1.0)
        self._jitter.setDecimals(3)
        self._jitter.setValue(0.1)
        mcmc_form.addRow("初始扰动比例", self._jitter)

        self._prior = QComboBox(self)
        self._prior.addItems(ESPEI_PRIORS)
        self._prior.currentTextChanged.connect(self._on_prior_changed)
        mcmc_form.addRow("先验", self._prior)

        self._prior_loc = QDoubleSpinBox(self)
        self._prior_loc.setRange(0.0, 1e6)
        self._prior_loc.setDecimals(3)
        self._prior_loc.setValue(1.0)
        self._prior_loc.setToolTip("normal 先验的 loc_relative：默认 1.0，即中心在当前参数值")
        mcmc_form.addRow("先验位置（相对参数值）", self._prior_loc)

        self._prior_scale = QDoubleSpinBox(self)
        self._prior_scale.setRange(0.0, 1e6)
        self._prior_scale.setDecimals(3)
        self._prior_scale.setValue(1.0)
        self._prior_scale.setToolTip("normal 先验的 scale_relative：默认 1.0")
        mcmc_form.addRow("先验尺度（相对参数值）", self._prior_scale)

        self._weights = QLineEdit("ZPF=1.0, ACR=1.0, HM=1.0, SM=1.0, CPM=1.0", self)
        self._weights.setToolTip("各类数据的权重；留空则用 ESPEI 默认值")
        mcmc_form.addRow("数据权重", self._weights)

        self._mcmc_box = mcmc_box
        layout.addWidget(mcmc_box)

        run_row = QHBoxLayout()
        self._btn_run = QPushButton(icon("run"), "运行 ESPEI", self)
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

        self._info = QLabel("尚未运行")
        self._info.setWordWrap(True)
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("ESPEI 的运行日志会出现在这里")
        self._log.setMaximumBlockCount(2000)
        layout.addWidget(self._log, 1)

        tail = QHBoxLayout()
        self._btn_open_dir = QPushButton("打开输出目录", self)
        self._btn_open_dir.setEnabled(False)
        self._btn_open_dir.clicked.connect(self._on_open_dir)
        self._btn_load = QPushButton("把产出的 TDB 载入主窗口", self)
        self._btn_load.setEnabled(False)
        self._btn_load.clicked.connect(self._on_load_result)
        tail.addWidget(self._btn_open_dir)
        tail.addWidget(self._btn_load)
        tail.addStretch(1)
        layout.addLayout(tail)

        # 模式切换时显隐 MCMC 专属设置
        self._mode.currentIndexChanged.connect(self._on_mode_changed)
        self._on_mode_changed(self._mode.currentIndex())
        self._on_prior_changed(self._prior.currentText())

    def _path_row(
        self,
        label: str,
        field: QLineEdit,
        kind: str,
        browse: Optional[Callable[[], None]],
        browse_btn: Optional[QPushButton] = None,
    ) -> QWidget:
        """造「输入框 + 浏览按钮」一行，返回承载它的控件。"""
        row = QWidget(self)
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.addWidget(field, 1)
        button = browse_btn
        if button is None:
            button = QPushButton(icon("open"), "…", self)
            button.setFixedWidth(28)
            if browse is not None:
                button.clicked.connect(browse)
        hbox.addWidget(button)
        field.setPlaceholderText(i18n.tr(f"点击「…」选择{kind}"))
        return row

    # ---------------------------------------------------------------- 浏览
    def _last_dir(self) -> str:
        if self._database is not None:
            return str(self._database.path.parent)
        return ""

    def _browse_datasets(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, i18n.tr("选择 ESPEI 数据集目录"), self._last_dir()
        )
        if path:
            self._datasets.setText(path)

    def _browse_phase_models(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("选择 phase_models 文件"), self._last_dir(),
            i18n.tr("JSON 相模型 (*.json);;所有文件 (*)"),
        )
        if path:
            self._phase_models.setText(path)

    def _browse_input_db(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("选择起始 TDB 数据库"), self._last_dir(),
            i18n.tr("热力学数据库 (*.tdb *.dat);;所有文件 (*)"),
        )
        if path:
            self._input_db.setText(path)

    def _browse_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.tr("ESPEI 产出的 TDB 保存位置"), self._last_dir() or "out.tdb",
            i18n.tr("热力学数据库 (*.tdb);;所有文件 (*)"),
        )
        if path:
            self._output_db.setText(path)

    # ---------------------------------------------------------------- 上下文
    def configure(self, database: Optional[LoadedDatabase], elements: List[str],
                  phases: List[str]) -> None:
        """记住当前数据库，仅用于给文件对话框一个合理的默认目录。"""
        self._database = database

    def _on_mode_changed(self, index: int) -> None:
        mode = ESPEI_MODES[index] if 0 <= index < len(ESPEI_MODES) else "generate"
        mcmc_only = mode == "mcmc"
        self._mcmc_box.setEnabled(mcmc_only)
        self._iterations.setEnabled(mcmc_only)
        self._aicc.setEnabled(not mcmc_only)
        self._btn_run.setText(i18n.tr(
            {"generate": "生成参数", "mcmc": "开始 MCMC 拟合",
             "check": "校验数据集"}[mode]
        ))

    def _on_prior_changed(self, text: str) -> None:
        normal = text == "normal"
        self._prior_loc.setEnabled(normal)
        self._prior_scale.setEnabled(normal)

    # ---------------------------------------------------------------- 运行
    def _collect(self) -> EspeiSettings:
        """把界面上的东西收成一个配置对象；非法输入在这里就地拦下。"""
        mode = ESPEI_MODES[self._mode.currentIndex()]
        weights_text = self._weights.text() if mode == "mcmc" else ""
        try:
            weights = _parse_data_weights(weights_text)
            tags = parse_tags(self._tags.text())
            aicc = parse_aicc_penalty(self._aicc.text()) if mode != "mcmc" else None
        except CalculationError as exc:
            raise exc
        prior = self._prior.currentText()
        return EspeiSettings(
            mode=mode,
            phase_models=self._phase_models.text().strip(),
            datasets=self._datasets.text().strip(),
            input_db=self._input_db.text().strip(),
            output_db=self._output_db.text().strip() or "espei_out.tdb",
            ref_state=self._ref_state.currentText(),
            excess_model=self._excess.currentText(),
            ridge_alpha=float(self._ridge.value()) if self._ridge.value() > 0 else None,
            tags=tags,
            aicc_penalty_factor=aicc,
            verbosity=1,
            iterations=int(self._iterations.value()),
            chains_per_parameter=int(self._chains.value()),
            chain_std_deviation=float(self._jitter.value()),
            cores=int(self._cores.value()),
            scheduler=str(self._scheduler.currentData()),
            prior=prior,
            prior_loc_relative=(
                float(self._prior_loc.value()) if prior == "normal" else None
            ),
            prior_scale_relative=(
                float(self._prior_scale.value()) if prior == "normal" else None
            ),
            data_weights=weights,
        )

    def _on_run(self) -> None:
        try:
            settings = self._collect()
            settings.validate()
        except CalculationError as exc:
            self._info.setText(f"⚠ {exc.user_message} — {exc.detail}")
            self.status.emit(exc.user_message)
            return

        self._result = None
        self._log.clear()
        self._append_log(f"# 模式：{ESPEI_MODE_LABELS[settings.mode]}")
        self._append_log(f"# 数据集：{settings.datasets}（{len(list_datasets(settings.datasets))} 个 .json）")

        self._worker = BaseWorker(_run_espei, settings)
        self._worker.context = f"ESPEI {settings.mode}"
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.succeeded.connect(self._on_success)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.cancelled.connect(self._on_cancelled)
        # log 不在 BaseWorker 的自动注入清单里，这里显式带上
        self._worker.kwargs["log"] = self._append_log

        self._btn_run.setEnabled(False)
        self._btn_cancel.setEnabled(True)
        self._progress.setValue(0)
        self._pool.start(self._worker)

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._append_log("# 收到取消请求，将在当前步骤结束后停止…")
            self.status.emit("正在取消…")

    def _on_progress(self, cur: int, total: int, msg: str) -> None:
        self._progress.setMaximum(max(1, total))
        self._progress.setValue(cur)
        if msg:
            self.status.emit(msg)

    def _append_log(self, text: str) -> None:
        """日志追加。后台线程调用，Qt 会把这个调用排队到主线程执行。"""
        self._log.appendPlainText(text)

    def _on_success(self, result: EspeiResult) -> None:
        self._result = result
        self._progress.setValue(self._progress.maximum())
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        have_db = result.output_db is not None
        self._btn_open_dir.setEnabled(have_db)
        self._btn_load.setEnabled(have_db)

        if result.mode == "check":
            self._info.setText(i18n.tr(
                f"✅ {result.n_datasets} 个数据集全部合法｜耗时 {result.elapsed_s:.1f} s"
            ))
            self.status.emit(f"ESPEI 数据集校验完成，{result.n_datasets} 个文件均合法")
            return

        assert result.output_db is not None
        self._info.setText(i18n.tr(
            f"✅ 参数已生成：{result.output_db.name}｜"
            f"载入数据集 {result.n_datasets} 个｜耗时 {result.elapsed_s:.1f} s"
        ))
        self.status.emit(f"ESPEI 完成，产物：{result.output_db}")
        self._append_log(i18n.tr(f"# 完成，产物：{result.output_db}"))
        # 拟合对比图（引擎里生成的「计算 vs 实验数据」）转交主窗口中央画布
        if getattr(result, "figure", None) is not None:
            self.figure_ready.emit(
                result.figure, list(result.axes),
                i18n.tr(f"ESPEI 拟合对比｜{result.output_db.stem}"),
            )

    def _on_failed(self, message: str, detail: str) -> None:
        self._progress.setValue(0)
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._info.setText(i18n.tr(f"❌ {message}\n{detail}"))
        self._append_log(i18n.tr(f"# 失败：{message}"))

    def _on_cancelled(self) -> None:
        self._progress.setValue(0)
        self._btn_run.setEnabled(True)
        self._btn_cancel.setEnabled(False)
        self._info.setText(i18n.tr("已取消"))
        self.status.emit("已取消")

    # ---------------------------------------------------------------- 收尾
    def _on_open_dir(self) -> None:
        result = self._result
        if result is None or result.output_db is None:
            return
        directory = str(result.output_db.parent)
        if os.name == "nt":  # pragma: no cover - 平台相关
            os.startfile(directory)  # type: ignore[attr-defined]
        else:  # pragma: no cover - 非 Windows
            import subprocess

            subprocess.run(["open", directory], check=False)

    def _on_load_result(self) -> None:
        result = self._result
        if result is None or result.output_db is None:
            return
        path = str(result.output_db)
        if not os.path.isfile(path):
            self._info.setText(i18n.tr(f"❌ 产物已不存在：{path}"))
            return
        self.database_ready.emit(path)
        self.status.emit(f"已把 {result.output_db.name} 载入主窗口")

    def apply_settings_defaults(self, database_dir: str) -> None:
        """载入数据库后给输出路径一个合理默认值。

        相对路径（如裸 ``out.tdb``）会落到工作目录而不是数据库旁边，用户下次打开
        会找不到产物，所以这里一旦还是占位值就换成数据库同目录的绝对路径。
        """
        current = self._output_db.text().strip()
        if database_dir and (not current or current == DEFAULT_OUTPUT_DB):
            self._output_db.setText(os.path.join(database_dir, DEFAULT_OUTPUT_DB))

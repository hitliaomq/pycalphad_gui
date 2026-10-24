"""宏命令页：像 Thermo-Calc 一样用脚本驱动整套计算。

页面只做三件事：编辑宏文本、把它交给后台线程、把执行过程的日志与结果
接回界面。真正的解释执行在 :mod:`core.macro_engine`，那里不依赖 Qt。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QThreadPool, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFontDatabase,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..core.database_manager import LoadedDatabase
from ..core.macro_engine import MacroResult, MacroSession, _COMMAND_ALIASES
from ..core.macro_help import (
    completion_words,
    diagram_types,
    help_overview,
    help_request,
)
from ..workers.macro_worker import MacroCommandWorker, MacroWorker
from .ht_tab import _cell_text

#: 宏文件扩展名（示例目录扫描与文件对话框共用）
MACRO_EXTS = (".pcm",)
#: 文件对话框过滤器
MACRO_FILTER = "宏文件 (*.pcm);;所有文件 (*)"

#: 帮助文本只放命令语法（ASCII），中文提示单独翻译
_HELP_SYNTAX = (
    "OPEN <TDB>   |   ELEMENTS AL ZN   |   PHASES *\n"
    "EXCLUDE <PHASE>   |   SWEEP ZN 0 1 0.02   |   FIXED T=600\n"
    "OPTIONS TIELINES=OFF GRID=ON STEP-Y=NP\n"
    "DIAGRAM BINARY | TERNARY | EQPLOT-BINARY | STEP | ISOPLETH\n"
    "PROPERTY GM VS ZN FROM 0 TO 1 STEP 0.02 T=600\n"
    "SCHEIL X(ZN)=0.3 START-T=850 STEP-T=1 LIQUID=LIQUID\n"
    "EQUILIBRIUM X(ZN)=0.3 START-T=850 STEP-T=1\n"
    "ESPEI GENERATE PHASE-MODELS=... DATASETS=... OUTPUT-DB=...\n"
    "HT OUTPUTS=stable_phases,gm_min PARALLEL=4\n"
    "EXPORT FIGURE result.png   |   EXPORT DATA result.csv\n"
    "PRINT / SET / INCLUDE / RESET / SHOW\n"
    "\n"
    "VARIABLES: $name = value   COMMENTS: # or //   CONTINUATION: \\\n"
)

#: 语法高亮认得的命令词（含常用别名）
_COMMAND_WORDS = {
    "OPEN", "LOAD", "ELEMENTS", "COMPONENTS", "PHASES", "PHASE", "EXCLUDE",
    "REJECT", "SWEEP", "CONDITIONS", "FIXED", "TEMPERATURE", "OPTIONS",
    "OPTION", "DIAGRAM", "BINARY", "TERNARY", "ISOTHERMAL", "EQPLOT-BINARY",
    "EQPLOT-TERNARY", "EQ-BINARY", "EQ-TERNARY", "STEP", "ISOPLETH",
    "PROPERTY", "SCHEIL", "SOLIDIFY", "EQUILIBRIUM", "EQ-SOLIDIFY", "ESPEI",
    "HT", "EXPORT", "SAVE", "WRITE", "PRINT", "ECHO", "SET", "INCLUDE",
    "RESET", "SHOW", "STATUS",
}

_COMMENT_RE = re.compile(r"(#|//).*$")
_FIRST_WORD_RE = re.compile(r"\s*([A-Za-z][A-Za-z0-9_\-]*)")
_VAR_RE = re.compile(r"\$[A-Za-z_]\w*")
_OPTION_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_\-().,/]*)(=)")
_NUMBER_RE = re.compile(r"(?<![\w.])[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")

#: 命令后面常见的键（Tab 补全用，全部 ASCII）
_OPTION_WORDS = {
    "OPTIONS": ["TIELINES=", "LABELS=", "GRID=", "AUTO-START=", "STEP-Y=", "FIG-SIZE="],
    "DIAGRAM": ["TIELINES=", "LABELS=", "GRID=", "AUTO-START=", "STEP-Y=", "FIG-SIZE="],
    "SCHEIL": ["X(", "START-T=", "STEP-T=", "STOP=", "ADAPTIVE=", "LIQUID=",
               "METHOD=", "COMPOSITION="],
    "EQUILIBRIUM": ["X(", "START-T=", "STEP-T=", "STOP=", "LIQUID=", "METHOD=",
                    "COMPOSITION="],
    "PROPERTY": ["GM", "HM", "SM", "CPM", "NP", "VS", "FROM", "TO", "STEP",
                 "T=", "X=", "SCOPE=", "PER-PHASE="],
    "FIXED": ["T=", "P=", "N=", "X("],
    "SWEEP": ["T", "P", "N"],
    "HT": ["OUTPUTS=", "PARALLEL=", "PROCESS="],
    "EXPORT": ["DPI="],
    "ESPEI": ["PHASE-MODELS=", "DATASETS=", "INPUT-DB=", "OUTPUT-DB=",
              "ITERATIONS=", "CORES=", "SCHEDULER=", "PRIOR=", "PRIOR-LOC=",
              "PRIOR-SCALE=", "WEIGHTS=", "TAGS=", "AICC=",
              "RIDGE=", "STD-DEV=", "CHAINS=", "VERBOSITY="],
}
#: 这些键的取值只有 ON / OFF
_BOOL_OPTIONS = {"TIELINES", "LABELS", "GRID", "AUTO-START", "ADAPTIVE", "PROCESS"}


class _CommandInput(QLineEdit):
    """命令行：Tab 交给补全，↑ / ↓ 翻历史。"""

    completion_requested = pyqtSignal()
    history_previous = pyqtSignal()
    history_next = pyqtSignal()

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 接口
        key = event.key()
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.completion_requested.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Up:
            self.history_previous.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Down:
            self.history_next.emit()
            event.accept()
            return
        super().keyPressEvent(event)


def macros_directory() -> Path:
    """项目内置示例宏目录（源码运行时位于仓库根目录下的 macros/）。"""
    root = Path(__file__).resolve().parents[2] / "macros"
    if root.is_dir():
        return root
    return Path.cwd() / "macros"


class _MacroHighlighter(QSyntaxHighlighter):
    """极简语法高亮：命令词、变量、选项键、数字、注释。"""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._comment = QTextCharFormat()
        self._comment.setForeground(QColor("#8a94a6"))
        self._comment.setFontItalic(True)
        self._command = QTextCharFormat()
        self._command.setForeground(QColor("#1f4fa8"))
        self._command.setFontWeight(700)
        self._variable = QTextCharFormat()
        self._variable.setForeground(QColor("#b35900"))
        self._option = QTextCharFormat()
        self._option.setForeground(QColor("#7a3e9d"))
        self._number = QTextCharFormat()
        self._number.setForeground(QColor("#0f7b6c"))

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt 接口
        code_end = len(text)
        comment = _COMMENT_RE.search(text)
        if comment is not None:
            code_end = comment.start()
            self.setFormat(code_end, len(text) - code_end, self._comment)
        code = text[:code_end]

        first = _FIRST_WORD_RE.match(code)
        if first is not None and first.group(1).upper() in _COMMAND_WORDS:
            self.setFormat(first.start(1), first.end(1) - first.start(1), self._command)
        for match in _VAR_RE.finditer(code):
            self.setFormat(match.start(), match.end() - match.start(), self._variable)
        for match in _OPTION_RE.finditer(code):
            self.setFormat(match.start(1), match.end(1) - match.start(1), self._option)
        for match in _NUMBER_RE.finditer(code):
            self.setFormat(match.start(), match.end() - match.start(), self._number)


class MacroTab(QWidget):
    """宏编辑 / 运行页。"""

    #: 状态栏消息
    status = pyqtSignal(str)
    #: (figure, axes 列表, 图注)
    figure_ready = pyqtSignal(object, object, str)
    #: 宏切换了数据库
    database_ready = pyqtSignal(str)
    #: (元素, 相) 选择变化
    selection_ready = pyqtSignal(list, list)
    #: 计算中 / 结束
    busy_changed = pyqtSignal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._database: Optional[LoadedDatabase] = None
        self._elements: List[str] = []
        self._phases: List[str] = []
        self._worker: Optional[MacroWorker | MacroCommandWorker] = None
        self._pool = QThreadPool.globalInstance()
        self._path: Optional[Path] = None
        self._examples: List[Path] = []
        self._base_dir = (
            macros_directory().parent if macros_directory().is_dir() else Path.cwd()
        )
        self._running = False
        #: 当前后台任务是交互式命令（True）还是整份宏（False）
        self._command_running = False
        #: 执行期间收到的结果图：(figure, axes, caption)
        self._pending_figure: Optional[tuple] = None
        #: 交互式会话；数据库 / 条件 / 变量跨命令保留
        self._session: Optional[MacroSession] = None
        self._session_db_path = ""
        #: 界面当前数据库（configure 推入），用来判断会话是否过期
        self._ui_db_path = ""
        self._history: List[str] = []
        self._history_pos = 0
        #: 连续按 Tab 时记住候选，便于在候选间轮换
        self._tab_state: Optional[dict] = None
        #: 日志 / 命令页的**原始中文**行：切语言时按新语言重放，
        #: 否则已经写进 QPlainTextEdit 的文本会停在切换前的语言
        self._log_lines: List[str] = []
        self._command_lines: List[str] = [
            "每行执行一条命令，状态会保留；输入 ? 查看帮助。"
        ]
        self._build_ui()
        self._load_examples()

    # ---------------------------------------------------------------- 界面
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        example_row = QHBoxLayout()
        self._examples_box = QComboBox(self)
        # 下拉项是文件路径（数据），不能让语言切换把 "phase" 之类的词翻成中文：
        # 中文片段翻不回英文，切回英文就会留下"相"这种半截路径
        self._examples_box.setProperty("i18nSkipText", True)
        self._examples_box.setToolTip(
            "内置的 pycalphad / scheil / ESPEI 官方示例"
        )
        # 路径很长：让 sizeHint 不参与布局，否则单这一项就能把右栏最小宽
        # 顶到 500px+，整个「计算」面板跟着变宽、画布被挤扁
        self._examples_box.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._examples_box.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._examples_box.setMinimumContentsLength(6)
        self._examples_box.setMinimumWidth(72)
        self._examples_box.currentIndexChanged.connect(self._on_example_chosen)
        example_row.addWidget(self._examples_box, 1)
        self._btn_open = QPushButton("打开宏…", self)
        self._btn_open.clicked.connect(self._on_open)
        example_row.addWidget(self._btn_open)
        layout.addLayout(example_row)

        file_row = QHBoxLayout()
        self._btn_save = QPushButton("保存", self)
        self._btn_save.clicked.connect(self._on_save)
        file_row.addWidget(self._btn_save)
        self._btn_save_as = QPushButton("另存为…", self)
        self._btn_save_as.clicked.connect(self._on_save_as)
        file_row.addWidget(self._btn_save_as)
        file_row.addStretch(1)
        self._path_label = QLabel(i18n.tr("未保存"), self)
        # 打开/保存后这里显示的是路径（数据），翻译只动 "未保存" 这一种措辞
        self._path_label.setProperty("i18nSkipText", True)
        self._path_label.setStyleSheet("color: #7a8494; font-size: 11px;")
        self._path_label.setWordWrap(True)
        file_row.addWidget(self._path_label)
        layout.addLayout(file_row)

        run_row = QHBoxLayout()
        self._btn_run = QPushButton("运行宏", self)
        self._btn_run.setObjectName("primary")
        self._btn_run.clicked.connect(self._on_run)
        self._btn_stop = QPushButton("停止", self)
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        # 帮助用 "?" 小按钮：英文 "Syntax Help" 单独就要 146px，和运行/停止
        # 并排会把页面的最小宽度重新顶到 360px+
        self._btn_help = QPushButton("?", self)
        self._btn_help.setFixedWidth(28)
        self._btn_help.setToolTip("语法帮助")
        self._btn_help.clicked.connect(self._on_help)
        run_row.addWidget(self._btn_run)
        run_row.addWidget(self._btn_stop)
        run_row.addWidget(self._btn_help)
        run_row.addStretch(1)
        layout.addLayout(run_row)

        self._editor = QPlainTextEdit(self)
        self._editor.setPlaceholderText("# 在此编写宏命令，或从上方选择示例")
        fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed.setPointSize(10)
        self._editor.setFont(fixed)
        self._editor.setTabStopDistance(28)
        self._highlighter = _MacroHighlighter(self._editor.document())

        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(5000)
        log_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        log_font.setPointSize(9)
        self._log.setFont(log_font)

        self._table = QTableWidget(self)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        # 交互式命令页：一行一条命令，文本输出留在本页，图走中央画布
        self._command_view = QPlainTextEdit(self)
        self._command_view.setReadOnly(True)
        self._command_view.setMaximumBlockCount(5000)
        self._command_view.setFont(log_font)
        self._command_view.setPlainText(i18n.tr(self._command_lines[0]))
        self._command_input = _CommandInput(self)
        self._command_input.setFont(fixed)
        self._command_input.setPlaceholderText(
            "输入宏命令，Enter 执行；? 帮助；Tab 补全"
        )
        self._command_input.returnPressed.connect(self._on_command_submitted)
        self._command_input.completion_requested.connect(self._on_tab_completion)
        self._command_input.history_previous.connect(self._history_back)
        self._command_input.history_next.connect(self._history_forward)
        self._command_input.textEdited.connect(self._on_command_edited)

        self._btn_command_run = QPushButton("执行", self)
        self._btn_command_run.clicked.connect(self._on_command_submitted)
        self._btn_command_reset = QPushButton("重置会话", self)
        self._btn_command_reset.setToolTip(
            "丢弃当前会话，下一条命令重新使用界面里的数据库与元素"
        )
        self._btn_command_reset.clicked.connect(self._on_command_reset)

        self._cmd_hint = QLabel("", self)
        self._cmd_hint.setStyleSheet("color: #7a8494; font-size: 11px;")
        self._cmd_hint.setWordWrap(True)

        command_panel = QWidget(self)
        command_layout = QVBoxLayout(command_panel)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(4)
        command_layout.addWidget(self._command_view, 1)
        command_row = QHBoxLayout()
        command_row.addWidget(self._command_input, 1)
        command_row.addWidget(self._btn_command_run)
        command_row.addWidget(self._btn_command_reset)
        command_layout.addLayout(command_row)
        command_layout.addWidget(self._cmd_hint)
        self._command_panel = command_panel

        self._result_tabs = QTabWidget(self)
        self._result_tabs.addTab(self._log, "输出日志")
        self._result_tabs.addTab(self._table, "结果表")
        self._result_tabs.addTab(command_panel, "命令")

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(self._editor)
        splitter.addWidget(self._result_tabs)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([320, 220])
        layout.addWidget(splitter, 1)

        self._progress = QProgressBar(self)
        self._progress.setFormat("%p%  %v/%m")
        self._progress.setValue(0)
        layout.addWidget(self._progress)

        self._info = QLabel("在编辑器中编写宏，或选择示例后点「运行宏」", self)
        self._info.setWordWrap(True)
        self._info.setStyleSheet("color: #7a8494;")
        layout.addWidget(self._info)

    # ---------------------------------------------------------------- 示例
    def _load_examples(self) -> None:
        directory = macros_directory()
        files: List[Path] = list(directory.rglob("*.pcm")) if directory.is_dir() else []
        self._examples = sorted(
            {p.resolve() for p in files if p.is_file()},
            key=lambda p: p.relative_to(directory).as_posix().lower(),
        )
        self._examples_box.blockSignals(True)
        self._examples_box.clear()
        self._examples_box.addItem(i18n.tr("（选择示例…）"), None)
        for path in self._examples:
            try:
                label = path.relative_to(directory).as_posix()
            except ValueError:
                label = path.name
            self._examples_box.addItem(label, str(path))
        self._examples_box.blockSignals(False)

    def _on_example_chosen(self, index: int) -> None:
        data = self._examples_box.itemData(index)
        if not data:
            return
        if not self._maybe_discard():
            self._examples_box.blockSignals(True)
            self._examples_box.setCurrentIndex(0)
            self._examples_box.blockSignals(False)
            return
        self._open_path(Path(data))
        # _open_path 会把下拉复位到占位项（外部打开文件时避免选中项失真）；
        # 从下拉进入时把选中项还回去，让人看得出编辑器里是哪份示例
        self._examples_box.blockSignals(True)
        self._examples_box.setCurrentIndex(index)
        self._examples_box.blockSignals(False)

    # ---------------------------------------------------------------- 文件
    def _maybe_discard(self) -> bool:
        if not self._editor.document().isModified():
            return True
        answer = QMessageBox.question(
            self,
            i18n.tr("未保存的宏"),
            i18n.tr("当前宏尚未保存，确定要放弃修改吗？"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_open(self) -> None:
        if not self._maybe_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("打开宏文件"), str(self._base_dir), i18n.tr(MACRO_FILTER)
        )
        if path:
            self._open_path(Path(path))

    def _open_path(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            i18n.warn(self, "无法读取宏文件", f"{path.name}\n{exc}")
            return
        self._editor.setPlainText(text)
        self._editor.document().setModified(False)
        self._path = path
        self._base_dir = path.parent
        self._update_path_label()
        if self._session is not None:
            self._session.set_base_dir(self._base_dir)
        self._examples_box.blockSignals(True)
        self._examples_box.setCurrentIndex(0)
        self._examples_box.blockSignals(False)
        self._info.setText(
            i18n.tr(f"已载入 {path.name}，点「运行宏」开始执行")
        )

    def _save_to(self, path: Path) -> bool:
        try:
            path.write_text(self._editor.toPlainText(), encoding="utf-8")
        except OSError as exc:
            i18n.warn(self, "保存失败", f"{path}\n{exc}")
            return False
        self._path = path
        self._base_dir = path.parent
        if self._session is not None:
            self._session.set_base_dir(self._base_dir)
        self._update_path_label()
        self._editor.document().setModified(False)
        self._info.setText(i18n.tr(f"已保存 {path}"))
        self._on_example_refresh()
        return True

    def _on_save(self) -> None:
        if self._path is None:
            self._on_save_as()
            return
        self._save_to(self._path)

    def _on_save_as(self) -> None:
        start = str(self._path) if self._path is not None else str(self._base_dir / "macro.pcm")
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.tr("保存宏文件"), start, i18n.tr(MACRO_FILTER)
        )
        if not path:
            return
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".pcm")
        self._save_to(target)

    def _on_example_refresh(self) -> None:
        """保存到 macros/ 下后，让新文件立刻出现在示例下拉里。"""
        try:
            self._examples_box.blockSignals(True)
            self._load_examples()
        finally:
            self._examples_box.blockSignals(False)

    # ---------------------------------------------------------------- 运行
    def configure(self, database: Optional[LoadedDatabase], elements: List[str],
                  phases: List[str]) -> None:
        """由主窗口推入当前上下文；宏里不写 OPEN / ELEMENTS 时沿用它们。"""
        self._database = database
        self._elements = list(elements or [])
        self._phases = list(phases or [])
        self._ui_db_path = str(database.path) if database is not None else ""

    def _on_run(self) -> None:
        if self._running:
            return
        text = self._editor.toPlainText().strip()
        if not text:
            self._info.setText(i18n.tr("宏内容为空，请先编写命令"))
            self.status.emit("宏内容为空")
            return
        self._command_running = False
        database_path = str(self._database.path) if self._database is not None else None
        self._worker = MacroWorker(
            text,
            base_dir=self._base_dir,
            database_path=database_path,
            elements=self._elements,
            phases=self._phases,
        )
        self._worker.signals.log.connect(self._append_log)
        self._worker.signals.status.connect(self._on_worker_status)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.figure.connect(self._on_figure)
        self._worker.signals.database.connect(self._on_database)
        self._worker.signals.selection.connect(self._on_selection)
        self._worker.signals.table.connect(self.show_result)
        self._worker.signals.succeeded.connect(self._on_success)
        self._worker.signals.failed.connect(self._on_failed)
        self._worker.signals.cancelled.connect(self._on_cancelled)

        self._log.clear()
        self._table.setRowCount(0)
        self._table.setColumnCount(0)
        self._pending_figure = None
        self._result_tabs.setCurrentWidget(self._log)
        self._progress.setMaximum(1)
        self._progress.setValue(0)
        self._set_running(True)
        self._info.setText(i18n.tr("正在执行宏…"))
        self._pool.start(self._worker)

    def _on_stop(self) -> None:
        if self._worker is None or not self._running:
            return
        self._worker.cancel()
        message = i18n.tr("# 收到取消请求，将在当前检查点停止…")
        if self._command_running:
            self._append_command(message)
        else:
            self._append_log(message)
        self.status.emit("正在取消…")

    def _set_running(self, running: bool) -> None:
        self._running = running
        self._btn_run.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._btn_open.setEnabled(not running)
        self._btn_save.setEnabled(not running)
        self._btn_save_as.setEnabled(not running)
        self._examples_box.setEnabled(not running)
        self._command_input.setEnabled(not running)
        self._btn_command_run.setEnabled(not running)
        self._btn_command_reset.setEnabled(not running)
        self.busy_changed.emit(running)

    def _append_log(self, text: str) -> None:
        self._log_lines.append(text)
        del self._log_lines[:-5000]
        self._log.appendPlainText(i18n.tr(text))

    def _on_worker_status(self, text: str) -> None:
        self.status.emit(text)

    def _on_progress(self, current: int, total: int, message: str) -> None:
        self._progress.setMaximum(max(1, total))
        self._progress.setValue(current)
        if message:
            self.status.emit(message)

    def _on_figure(self, figure, axes, caption: str) -> None:
        # 执行期间不立刻挂到中央画布：worker 后面还可能对同一张 Figure 执行
        # EXPORT FIGURE（savefig）。一旦主线程把它包成 FigureCanvasQTAgg，
        # worker 线程再 savefig 就会跨线程碰 QWidget，PyQt 抛
        # "super-class __init__() of type FigureCanvasQTAgg was never called"，
        # 导出失败、画布还会被回写成 Agg 而空白。先存着，worker 结束后再交付。
        self._pending_figure = (figure, axes, caption)

    def _flush_figure(self) -> None:
        """把执行期间攒下的结果图交给主窗口（worker 已结束）。"""
        pending, self._pending_figure = self._pending_figure, None
        if pending is not None:
            self.figure_ready.emit(*pending)

    def _on_database(self, path: str) -> None:
        if self._command_running:
            # 交互式会话自己 OPEN 的库：主窗口随后会 configure 一遍，
            # 记住它，避免下一条命令误判"界面换了库"而重置会话
            self._session_db_path = str(path)
        self.database_ready.emit(path)

    def _on_selection(self, elements: List[str], phases: List[str]) -> None:
        self._elements = list(elements)
        self._phases = list(phases)
        self.selection_ready.emit(list(elements), list(phases))

    def _on_success(self, result: MacroResult) -> None:
        self._flush_figure()
        self._set_running(False)
        self._progress.setValue(self._progress.maximum())
        if result.cancelled:
            self._info.setText(i18n.tr("已取消：宏在检查点停止。"))
            self.status.emit("已取消")
            return
        tail = (
            i18n.tr(f"，输出 {len(result.outputs)} 个文件")
            if result.outputs else ""
        )
        self._info.setText(i18n.tr(
            f"完成 {result.n_commands} 条命令、{result.n_results} 个结果{tail}｜"
            f"耗时 {result.elapsed_s:.1f} s"
        ))
        self.status.emit("宏执行完成")

    def _on_failed(self, message: str, detail: str) -> None:
        # 失败前的图也保留：至少能看到已经算出来的那部分
        self._flush_figure()
        self._set_running(False)
        self._progress.setValue(0)
        self._info.setText(f"❌ {message}\n{detail}")
        self._append_log(i18n.tr(f"# 失败：{message}"))
        self.status.emit("宏执行失败")

    def _on_cancelled(self) -> None:
        self._flush_figure()
        self._set_running(False)
        self._progress.setValue(0)
        self._info.setText(i18n.tr("已取消"))
        self.status.emit("已取消")

    # ---------------------------------------------------------------- 命令面板
    def _append_command(self, text: str) -> None:
        self._command_lines.append(text)
        del self._command_lines[:-5000]
        self._command_view.appendPlainText(i18n.tr(text))

    def retranslate(self) -> None:
        """语言切换后按原始中文重放日志 / 命令页。

        这两个框是只读多行文本，``i18n.apply_to`` 刻意不碰（里面大多是运行
        数据）；但"运行数据之外的固定措辞"仍要跟着界面语言走。
        """
        self._log.setPlainText("\n".join(i18n.tr(t) for t in self._log_lines))
        self._command_view.setPlainText(
            "\n".join(i18n.tr(t) for t in self._command_lines)
        )
        self._update_path_label()
        if self._examples_box.count():
            self._examples_box.setItemText(0, i18n.tr("（选择示例…）"))

    def _update_path_label(self) -> None:
        self._path_label.setText(
            str(self._path) if self._path is not None else i18n.tr("未保存")
        )

    def _on_command_edited(self, _text: str) -> None:
        self._cmd_hint.clear()
        self._tab_state = None

    def _on_command_submitted(self) -> None:
        if self._running:
            return
        raw = self._command_input.text().strip()
        if not raw:
            return
        self._command_input.clear()
        self._cmd_hint.clear()
        self._tab_state = None
        self._history.append(raw)
        self._history_pos = len(self._history)
        self._append_command(f"> {raw}")

        is_help, text, query = help_request(raw)
        if is_help:
            if text is None:
                self._append_command(f"未知命令：{query}。输入 ? 查看全部命令。")
            else:
                self._append_command(text)
            self._command_input.setFocus()
            return
        self._run_command(raw)

    def _run_command(self, text: str) -> None:
        # 界面换过数据库 → 旧会话的 OPEN 结果已经不对，自动重开
        if (self._session is not None and self._session_db_path
                and self._ui_db_path
                and self._session_db_path != self._ui_db_path):
            self._reset_command_session()
        if self._session is None:
            self._session = MacroSession(
                base_dir=self._base_dir,
                initial_database=self._ui_db_path or None,
                initial_elements=self._elements,
                initial_phases=self._phases,
            )
            self._session_db_path = self._ui_db_path
        self._command_running = True
        self._worker = MacroCommandWorker(self._session, text)
        signals = self._worker.signals
        signals.log.connect(self._append_command)
        signals.status.connect(self._on_worker_status)
        signals.progress.connect(self._on_progress)
        signals.figure.connect(self._on_figure)
        signals.database.connect(self._on_database)
        signals.selection.connect(self._on_selection)
        signals.table.connect(self._on_command_table)
        signals.succeeded.connect(self._on_command_success)
        signals.failed.connect(self._on_command_failed)
        signals.cancelled.connect(self._on_command_cancelled)

        self._pending_figure = None
        self._progress.setMaximum(1)
        self._progress.setValue(0)
        self._set_running(True)
        self._info.setText(i18n.tr("正在执行命令…"))
        self._pool.start(self._worker)

    def _on_command_success(self, result: MacroResult) -> None:
        self._flush_figure()
        self._set_running(False)
        self._command_running = False
        if self._session is not None and self._session.database is not None:
            self._session_db_path = str(self._session.database.path)
        if result.cancelled:
            self._append_command(i18n.tr("已取消"))
            self._info.setText(i18n.tr("已取消"))
            self.status.emit("已取消")
            self._command_input.setFocus()
            return
        self._progress.setValue(self._progress.maximum())
        tail = f"｜{len(result.outputs)} 个文件" if result.outputs else ""
        self._append_command(f"✓ {result.elapsed_s:.2f} s{tail}")
        self._info.setText(i18n.tr(f"命令执行完成｜耗时 {result.elapsed_s:.2f} s"))
        self.status.emit("命令执行完成")
        self._command_input.setFocus()

    def _on_command_failed(self, message: str, detail: str) -> None:
        # 失败前的图也保留：至少能看到已经算出来的那部分
        self._flush_figure()
        self._set_running(False)
        self._command_running = False
        self._progress.setValue(0)
        self._append_command(f"✗ {message}")
        if detail:
            self._append_command("  " + detail)
        self._info.setText(i18n.tr(f"命令失败：{message}"))
        self.status.emit("命令执行失败")
        self._command_input.setFocus()

    def _on_command_cancelled(self) -> None:
        self._flush_figure()
        self._set_running(False)
        self._command_running = False
        self._progress.setValue(0)
        self._append_command(i18n.tr("已取消"))
        self._info.setText(i18n.tr("已取消"))
        self.status.emit("已取消")
        self._command_input.setFocus()

    def _on_command_reset(self) -> None:
        if self._running:
            return
        self._reset_command_session()

    def _reset_command_session(self) -> None:
        self._session = None
        self._session_db_path = ""
        self._append_command(i18n.tr(
            "# 会话已重置，下一条命令会沿用界面当前的数据库与元素"
        ))

    def _on_command_table(self, frame, title: str = "") -> None:
        self.show_result(frame, title, focus=False)
        if title:
            self._append_command(f"# 结果表已更新：{title}")
        else:
            self._append_command("# 结果表已更新")

    # ---------------------------------------------------------------- 历史 / 补全
    def _history_back(self) -> None:
        if not self._history:
            return
        self._history_pos = max(0, self._history_pos - 1)
        self._command_input.setText(self._history[self._history_pos])
        self._command_input.setCursorPosition(len(self._command_input.text()))

    def _history_forward(self) -> None:
        if not self._history:
            return
        self._history_pos = min(len(self._history), self._history_pos + 1)
        if self._history_pos >= len(self._history):
            self._command_input.clear()
            return
        self._command_input.setText(self._history[self._history_pos])
        self._command_input.setCursorPosition(len(self._command_input.text()))

    def _on_tab_completion(self) -> None:
        text = self._command_input.text()
        pos = self._command_input.cursorPosition()
        start = pos
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        end = pos
        while end < len(text) and not text[end].isspace():
            end += 1
        prefix = text[start:pos]
        token = text[start:end]
        prior = text[:start].split()

        state = self._tab_state
        if (state is not None and state["start"] == start
                and token in state["matches"]):
            # 同一个位置反复按 Tab：在候选之间轮换
            matches = state["matches"]
            index = (matches.index(token) + 1) % len(matches)
        else:
            words = self._completion_words(prior, prefix)
            matches = [w for w in words if w.upper().startswith(prefix.upper())]
            index = 0
        if not matches:
            self._cmd_hint.setText(i18n.tr("没有匹配的候选"))
            self._tab_state = None
            return

        chosen = matches[index]
        self._tab_state = {"start": start, "matches": matches}
        self._command_input.setText(text[:start] + chosen + text[end:])
        self._command_input.setCursorPosition(start + len(chosen))
        hint = f"{len(matches)} 个候选（再按 Tab 切换）：" + "  ".join(matches[:8])
        if len(matches) > 8:
            hint += "  …"
        self._cmd_hint.setText(i18n.tr(hint))

    def _completion_words(self, prior: List[str], prefix: str) -> List[str]:
        if prefix.startswith("$"):
            variables = self._session.variables if self._session else {}
            return ["$" + name for name in sorted(variables)]
        if not prior:
            return completion_words()
        command = prior[0].upper()
        command = _COMMAND_ALIASES.get(command, command)
        elements: List[str] = []
        if self._database is not None:
            elements = [e.upper() for e in self._database.display_elements]

        if command in ("OPEN", "INCLUDE"):
            return self._path_words(prefix)
        if command == "ELEMENTS":
            return elements + ["*", "ALL"]
        if command in ("PHASES", "EXCLUDE"):
            return list(self._phases)
        if command == "DIAGRAM":
            return diagram_types()
        if command == "ESPEI":
            return ["GENERATE", "MCMC", "CHECK"] + _OPTION_WORDS["ESPEI"]
        if command == "EXPORT":
            if prior[-1].upper() in ("FIGURE", "IMAGE", "PLOT", "DATA", "TABLE"):
                return self._path_words(prefix)
            return (["FIGURE", "DATA", "PNG", "SVG", "PDF", "JPG", "CSV", "XLSX"]
                    + self._path_words(prefix))
        if "=" in prefix:
            key = prefix.split("=", 1)[0].strip()
            if key.upper() in _BOOL_OPTIONS:
                return [key + "=" + value for value in ("ON", "OFF")]

        words = list(_OPTION_WORDS.get(command, ()))
        if command in ("SWEEP", "FIXED", "PROPERTY"):
            words += elements
        return words

    def _path_words(self, prefix: str) -> List[str]:
        text = prefix.replace("\\", "/")
        cut = text.rfind("/")
        rel_dir = text[:cut] if cut >= 0 else ""
        head = text[:cut + 1] if cut >= 0 else ""
        directory = Path(rel_dir) if rel_dir else Path(".")
        if not directory.is_absolute():
            directory = self._base_dir / directory
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return []
        words: List[str] = []
        for entry in entries:
            if entry.name.startswith("."):
                continue
            name = head + entry.name
            if entry.is_dir():
                name += "/"
            words.append(name)
            if len(words) >= 200:
                break
        return words

    # ---------------------------------------------------------------- 结果表
    def show_result(self, frame, title: str = "", focus: bool = True) -> None:
        """把宏产生的结果表填进「结果表」页（DataFrame 与列名保持原样）。"""
        columns = list(frame.columns)
        self._table.setColumnCount(len(columns))
        self._table.setHorizontalHeaderLabels([i18n.tr(str(c)) for c in columns])
        self._table.setRowCount(len(frame))
        for r in range(len(frame)):
            for c, column in enumerate(columns):
                self._table.setItem(
                    r, c, QTableWidgetItem(_cell_text(frame.iat[r, c]))
                )
        if focus:
            self._result_tabs.setCurrentWidget(self._table)
        if title:
            self._result_tabs.setTabText(1, i18n.tr(title))

    # ---------------------------------------------------------------- 帮助
    def _on_help(self) -> None:
        QMessageBox.information(
            self,
            i18n.tr("宏命令语法"),
            i18n.tr("命令大小写不敏感，参数可用单双引号包住。")
            + "\n\n" + i18n.tr(help_overview()) + "\n\n" + _HELP_SYNTAX,
        )


__all__ = ["MacroTab", "macros_directory", "MACRO_FILTER", "MACRO_EXTS"]

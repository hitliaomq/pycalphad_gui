"""主窗口。

界面按「**相图为对象**」的原则重排：

```
┌─────────────────────────────────────────────────────────────┐
│ 工具栏（图标）：打开 · 计算 · 取消 · 导出 · 复位 · 清除 · 对轴  │
├──────────┬───────────────────────────────────┬──────────────┤
│ 元素      │                                   │ 相图条件      │
│ 周期表    │        相图画布（主体，占 60%+）      │ 属性          │
│ ───────── │                                   │ 高通量        │
│ 相列表    │                                   │              │
├──────────┴───────────────────────────────────┴──────────────┤
│ 状态栏：体系 · 光标坐标 · 提示                                │
└─────────────────────────────────────────────────────────────┘
```

三个面板都是停靠面板，关掉后画布自动铺满窗口（"视图"菜单里能再叫回来）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np
from PIL import Image
from PyQt6.QtCore import QSettings, QSize, Qt
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QFrame,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..core.database_manager import LoadedDatabase, load_database
from ..core.diagnostics import CalculationError
from ..config import APP_NAME, APP_VERSION, VACANCY
from .diagram_panel import DiagramPanel
from .diagram_view import DiagramView
from .digitize_canvas import DigitizeCanvas
from .digitize_tab import DigitizeTab
from .ht_tab import HighThroughputTab
from .espei_tab import EspeiTab
from .macro_tab import MacroTab
from .phase_list import PhaseListWidget
from .periodic_table import PeriodicTableWidget
from .property_tab import PropertyTab
from .scheil_tab import ScheilTab
from .theme import application_icon, icon

logger = logging.getLogger(__name__)

#: 数据库文件过滤器
DB_FILTER = "Thermo-Calc 数据库 (*.tdb *.dat);;所有文件 (*)"
#: 可拖拽进入窗口的扩展名（数据库 + 相图位图）
DB_EXTS = (".tdb", ".dat")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
#: 图像文件过滤器
IMAGE_FILTER = "图像文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;所有文件 (*)"
#: QSettings 中存放"上次打开的目录"的键
_LAST_DIR_KEY = f"{APP_NAME.replace(' ', '_')}/last_dir"
#: 工具栏图标边长
ICON_PX = 18


def _load_last_dir() -> str:
    """读取上次打开数据库的目录（读不到就用用户目录）。"""
    try:
        return QSettings().value(_LAST_DIR_KEY, "", type=str) or str(Path.home())
    except Exception:  # noqa: BLE001
        logger.debug("读取上次目录失败，回退到用户目录", exc_info=True)
        return str(Path.home())


def _coerce_image_array(source: object) -> np.ndarray:
    """路径 / QImage / QPixmap / ndarray → ``uint8`` RGB 数组。

    统一在这里做转换，主窗口和拖拽入口共用；PIL 只在**读文件**时用
    （它打开失败会抛 OSError，交给调用方转成中文提示）。
    """
    from PIL import Image
    from PyQt6.QtGui import QImage, QPixmap  # 局部导入：避免循环依赖

    from ..core.digitizer import image_to_array

    image: Optional[Image.Image] = None
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            raise ValueError(f"文件不存在：{path}")
        image = Image.open(path)
        # 扫描件常见 CMYK / 调色板模式，绘图库只认 RGB(A)
        image.load()
    elif isinstance(source, QImage):
        from .digitize_canvas import pixmap_to_array

        return pixmap_to_array(QPixmap.fromImage(source))
    elif isinstance(source, QPixmap):
        from .digitize_canvas import pixmap_to_array

        return pixmap_to_array(source)
    elif isinstance(source, Image.Image):
        image = source
    else:
        return image_to_array(source)
    return image_to_array(image)


def _save_last_dir(directory: Path) -> None:
    """记录本次打开的目录，下次启动直接定位到这里。"""
    try:
        QSettings().setValue(_LAST_DIR_KEY, str(directory))
    except Exception:  # noqa: BLE001
        logger.debug("写入上次目录失败", exc_info=True)



def _relax_min_widths(root: QWidget) -> None:
    """把"文本驱动的最小宽"超标的控件显式压回 240px。

    QLayout 计算最小尺寸时，控件的显式 minimumWidth 优先于 minimumSizeHint，
    所以对最小宽超标的复选框 / 组合框 / 分组框 / 按钮调一次 setMinimumWidth，
    表单就能在窄面板里收缩（文本超出部分被裁剪），而不是把停靠面板撑到
    1700px+、把最大化窗口顶出屏幕。英文译文比中文长得多，这一步必不可少。
    """
    from PyQt6.QtWidgets import QCheckBox, QComboBox, QGroupBox, QPushButton

    # 按钮给更小的上限：一行经常并排两个按钮，240+240 直接顶爆行宽
    caps = ((QPushButton, 150), (QComboBox, 240), (QCheckBox, 240), (QGroupBox, 240))
    for w in root.findChildren(QWidget):
        for cls, cap in caps:
            if isinstance(w, cls):
                try:
                    hint = w.minimumSizeHint().width()
                except RuntimeError:  # 控件已被销毁
                    continue
                if hint > cap:
                    w.setMinimumWidth(cap)
                break


class MainWindow(QMainWindow):
    """应用主窗口。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # 语言必须在**造控件之前**定下来：控件带的是源码里的中文原文，
        # 建完再整树翻一遍即可；若先建再设语言，中途构造出来的默认文本
        # 会以中文形态留在界面上。
        i18n.set_lang(i18n.load_saved_lang())
        logo = application_icon()
        if not logo.isNull():
            self.setWindowIcon(logo)
        self._database: Optional[LoadedDatabase] = None
        self._last_dir = _load_last_dir()
        #: 最近一次状态栏消息的中文原文——切语言时用它重翻一遍
        self._last_status = "请先打开一个 TDB / DAT 热力学数据库"
        self._set_window_title()
        self._build_ui()
        # 顺序有讲究：菜单和工具栏引用同一批 QAction，
        # 所以必须先 _build_toolbar 把动作造出来，再 _build_menu 接上去。
        self._build_toolbar()
        self._build_menu()
        self._build_language_button()
        self._apply_language()
        # 英文译文比中文长：把"文本驱动的最小宽"超标的控件显式压回 240px，
        # 否则右侧面板最小宽 1762px、窗口最小 4914px，最大化也塞不进屏幕
        _relax_min_widths(self._left_dock)
        _relax_min_widths(self._right_dock)
        screen = self.screen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(
                min(1440, int(avail.width() * 0.92)),
                min(900, int(avail.height() * 0.92)),
            )
        else:
            self.resize(1440, 900)

    # ---------------------------------------------------------------- 语言
    def _build_language_button(self) -> None:
        """把语言切换按钮挂到菜单栏右上角（与菜单同一行，永远可见）。

        放在这里而不是右侧标签栏的角落：右侧"计算"面板可以被用户隐藏，
        按钮跟着消失就没法切回来了。
        """
        btn = QToolButton(self)
        btn.setObjectName("langButton")
        btn.setIcon(icon("lang"))
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip(i18n.tr("切换界面语言"))
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
        for code in i18n.LANGS:
            # 语言自称不进词典，所以这两个菜单项在任何语言下都显示原样
            act = menu.addAction(i18n.LANG_NAMES[code])
            act.setCheckable(True)
            act.setChecked(code == i18n.lang())
            act.triggered.connect(lambda _checked, c=code: self.set_language(c))
        btn.setMenu(menu)
        self._lang_button = btn
        self._lang_menu = menu
        self.menuBar().setCornerWidget(btn, Qt.Corner.TopRightCorner)

    def _sync_language_button(self) -> None:
        """按钮文字跟着当前语言走（自称：English / 中文）。"""
        code = i18n.lang()
        self._lang_button.setText(i18n.LANG_NAMES[code])
        for act in self._lang_menu.actions():
            act.setChecked(act.text() == i18n.LANG_NAMES[code])

    def set_language(self, code: str) -> None:
        """切换界面语言：整树翻译 + 刷新代码生成的内容 + 重画图表文字。"""
        if code == i18n.lang() or code not in i18n.LANGS:
            return
        i18n.set_lang(code)
        i18n.save_lang(code)
        i18n.apply_to(self)              # ① 现有控件的静态文案
        self._retranslate_dynamic()      # ② 代码生成的下拉项 / 表格 / 标签
        i18n.notify_changed(code)        # ③ 各面板自己的动态内容
        self._sync_language_button()
        self._on_status("界面语言已切换。")

    def _apply_language(self) -> None:
        """启动时套用已保存的语言（默认英文）。"""
        i18n.apply_to(self)
        self._retranslate_dynamic()
        self._sync_language_button()

    def _retranslate_dynamic(self) -> None:
        """翻译"代码生成"的内容——整树遍历扫不到的那些。"""
        self._set_window_title()
        self._table.retranslate()
        self._refresh_comps_label()
        self._on_status(self._last_status)
        # matplotlib 的 Text 不是 QWidget，需要单独走一遍（相图轴题、图例）
        self._view.retranslate()
        # 宏页的日志 / 命令回显是只读多行文本，整树遍历会跳过；按原始中文重放
        self._macro_tab.retranslate()

    def _set_window_title(self) -> None:
        suffix = f" — {self._database.name}" if self._database else ""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}{suffix}")

    def _new_dock(self, title: str) -> Tuple[QDockWidget, QWidget]:
        """造一个停靠面板，返回 (面板, 内容控件)。"""
        content = QWidget(self)
        content.setProperty("dockPane", True)
        dock = QDockWidget(title, self)
        dock.setWidget(content)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        return dock, content

    def _fill_dock(self, content: QWidget, widgets: List[QWidget],
                   stretch: Optional[List[int]] = None) -> None:
        """把控件按给定拉伸比例塞进停靠面板。"""
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(0)
        ratios = stretch or [1] * len(widgets)
        for widget, ratio in zip(widgets, ratios):
            layout.addWidget(widget, ratio)

    def _wrap_side_page(self, page: QWidget) -> QScrollArea:
        """把右侧子页面放进滚动区，切断页面最小尺寸对窗口的绑架。

        QTabWidget 的最小尺寸取**所有页面**的并集：ESPEI 页整表单需要 826px
        高、宏页一行按钮需要 800px+ 宽，结果整窗最小高被抬到 1000px 以上，
        笔记本上最大化也塞不进屏幕，底部的进度条与日志被挤到屏幕外。放进
        QScrollArea 后页面该多大还多大，窗口不够时由滚动条兜底，窗口本身
        可以按显示器可用区域自由缩放。
        """
        area = QScrollArea(self)
        area.setObjectName("sideScroll")
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidgetResizable(True)
        area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        area.viewport().setAutoFillBackground(False)
        area.setWidget(page)
        return area

    def _side_index(self, page: QWidget) -> int:
        """页面在右栏标签页里的下标（页面外面包了滚动区）。"""
        return self._side_tabs.indexOf(self._side_scrolls.get(page, page))

    def _side_show(self, page: QWidget) -> None:
        """切到右栏的某个页面（自动跳过滚动区包装）。"""
        self._side_tabs.setCurrentWidget(self._side_scrolls.get(page, page))

    def _build_ui(self) -> None:
        # ---------------- 中央：相图（主角） ----------------
        self._view = DiagramView(self)
        self._view.status.connect(self._on_status)

        self._empty = self._build_empty_state()
        self._canvas_host = QWidget(self)
        host_layout = QVBoxLayout(self._canvas_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.addWidget(self._view)

        # ---------------- 中央第二页：导入的相图位图（供数字化） ----------------
        self._image_canvas = DigitizeCanvas(self)
        self._image_host = QWidget(self)
        img_layout = QVBoxLayout(self._image_host)
        img_layout.setContentsMargins(0, 0, 0, 0)
        img_layout.setSpacing(0)
        img_layout.addWidget(self._image_canvas, 1)
        self._image_hint = QLabel(
            "滚轮缩放 · 中键拖动平移 · 左键取点 · 右键删点（数字化流程见右侧「数字化相图」）"
        )
        self._image_hint.setWordWrap(True)
        self._image_hint.setStyleSheet("color: #7a8494; font-size: 11px; padding: 4px 10px;")
        img_layout.addWidget(self._image_hint)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._canvas_host)
        self._stack.addWidget(self._image_host)
        self._stack.setCurrentWidget(self._empty)
        self.setCentralWidget(self._stack)

        # ---------------- 左侧 dock：元素 + 相 ----------------
        self._table = PeriodicTableWidget(self)
        self._table.selection_changed.connect(self._on_elements_changed)

        self._phase_list = PhaseListWidget(self)
        self._phase_list.selection_changed.connect(self._on_phases_changed)

        left_dock, left_content = self._new_dock("元素与相")
        self._fill_dock(left_content, [self._table, self._phase_list], [0, 1])
        left_dock.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)
        self._left_dock = left_dock

        # ---------------- 右侧 dock：条件 / 属性 / 高通量 ----------------
        self._diagram_panel = DiagramPanel(self)
        self._diagram_panel.status.connect(self._on_status)
        self._diagram_panel.result_ready.connect(self._view.set_result)
        self._diagram_panel.notice.connect(self._view.notice)
        # 注意：busy_changed 的接收者是工具栏上的"取消"动作，
        # 它要到 _build_toolbar 里才创建，所以连接必须放在那之后。

        self._property_tab = PropertyTab(self)
        self._ht_tab = HighThroughputTab(self)
        self._scheil_tab = ScheilTab(self)
        self._espei_tab = EspeiTab(self)
        self._macro_tab = MacroTab(self)
        self._digitize_tab = DigitizeTab(self)
        # 属性 / ESPEI / Scheil / 宏的结果图统一画到主窗口中央画布
        self._property_tab.figure_ready.connect(self._show_result_figure)
        self._espei_tab.figure_ready.connect(self._show_result_figure)
        self._scheil_tab.figure_ready.connect(self._show_result_figure)
        self._macro_tab.figure_ready.connect(self._show_result_figure)
        self._scheil_tab.status.connect(self._on_status)
        self._espei_tab.status.connect(self._on_status)
        self._macro_tab.status.connect(self._on_status)
        # 宏里的 OPEN / ESPEI 产物可以换掉当前数据库
        self._macro_tab.database_ready.connect(self._on_espei_database_ready)
        # 宏脚本选择的元素 / 相同步到左侧面板
        self._macro_tab.selection_ready.connect(self._on_macro_selection)

        self._side_tabs = QTabWidget(self)
        self._side_scrolls: dict[QWidget, QScrollArea] = {}
        for page, title in (
            (self._diagram_panel, "相图计算"),
            (self._macro_tab, "宏命令"),
            (self._property_tab, "属性"),
            (self._ht_tab, "高通量"),
            (self._scheil_tab, "Scheil 凝固"),
            (self._espei_tab, "ESPEI 拟合"),
            (self._digitize_tab, "数字化相图"),
        ):
            scroll = self._wrap_side_page(page)
            self._side_scrolls[page] = scroll
            self._side_tabs.addTab(scroll, title)
        self._side_tabs.setDocumentMode(True)
        # 子页面有 6 个，窄面板里一字排开必然放不下：关掉"平铺展开"、
        # 开启省略号与滚动箭头（放不下时出现 ◀ ▶，不再把最后一页挤没）
        self._side_tabs.setObjectName("sideTabs")
        self._side_tabs.setUsesScrollButtons(True)
        self._side_tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self._side_tabs.tabBar().setExpanding(False)
        # drawBase 是标签栏底部那条通长基线：documentMode + pane 无边框时，
        # 它会从标签之间的缝隙里透出来，看起来像一段段"—"。关掉。
        self._side_tabs.tabBar().setDrawBase(False)
        for idx in range(self._side_tabs.count()):
            self._side_tabs.setTabEnabled(idx, False)
        # 数字化不依赖数据库（图是外部导入的）；宏页也不依赖——OPEN 是宏
        # 自己的命令，用户可以先运行宏再载入数据库。这两页始终可用。
        for tab in (self._digitize_tab, self._macro_tab):
            self._side_tabs.setTabEnabled(self._side_index(tab), True)
        # 默认停在「相图计算」：这是用户 90% 时间要用的那一页，
        # 免得每次开界面都要手动切一次。
        self._side_tabs.setCurrentIndex(self._side_index(self._diagram_panel))
        self._digitize_tab.status.connect(self._on_status)
        self._digitize_tab.attach_canvas(self._image_canvas)

        right_dock, right_content = self._new_dock("计算")
        self._fill_dock(right_content, [self._side_tabs])
        right_dock.setMinimumWidth(240)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_dock)
        self._right_dock = right_dock

        # ---------------- 状态栏 ----------------
        self._status = self.statusBar()
        self._status_label = QLabel("请先打开一个 TDB / DAT 热力学数据库")
        self._status_label.setWordWrap(True)
        self._status.addWidget(self._status_label, 1)
        self._comps_label = QLabel("")
        self._comps_label.setStyleSheet("color: #2f6feb; font-weight: 600; padding-right: 10px;")
        self._status.addPermanentWidget(self._comps_label)

        self.setAcceptDrops(True)

    def _build_empty_state(self) -> QWidget:
        """未载入数据库时盖在画布上的引导卡。"""
        card = QWidget(self)
        card.setObjectName("emptyCard")
        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon_label = QLabel()
        logo = application_icon()
        if not logo.isNull():
            icon_label.setPixmap(logo.pixmap(64, 64))
        else:
            icon_label.setPixmap(icon("info", 56).pixmap(56, 56))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("尚未载入数据库")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")

        tip = QLabel(
            "载入后即可看相图：<br>"
            "元素周期表挑组分 → 相列表决定算哪些相 → 点「计算并绘制」"
        )
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #7a8494;")

        btn = QPushButton(icon("open"), "打开数据库…", card)
        btn.setObjectName("primary")
        btn.setMinimumSize(190, 38)
        btn.setToolTip("快捷键 Ctrl+O；也可以直接把 .tdb 文件拖进窗口")
        btn.clicked.connect(self._on_open_database)

        shortcut = QLabel("Ctrl+O，或把 .tdb 拖进窗口")
        shortcut.setWordWrap(True)
        shortcut.setStyleSheet("color: #a5acba; font-size: 11px;")
        shortcut.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for widget in (icon_label, title, tip, btn, shortcut):
            layout.addWidget(widget)
        return card

    # ---------------------------------------------------------------- 工具栏
    def _build_toolbar(self) -> None:
        toolbar: QToolBar = QToolBar("主工具栏", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(ICON_PX, ICON_PX))
        toolbar.setFixedHeight(42)
        self.addToolBar(toolbar)

        def add_action(name: str, text: str, tip: str, shortcut: str,
                       callback: Callable[[], None]) -> QAction:
            act = QAction(icon(name), text, self)
            act.setToolTip(tip)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(callback)
            toolbar.addAction(act)
            return act

        self._act_open = add_action("open", "打开数据库…", "载入 TDB / DAT 数据库", "Ctrl+O",
                                    self._on_open_database)
        self._act_import = add_action(
            "image", "导入图像", "导入一张相图图片用于数字化（Ctrl+Shift+O）",
            "Ctrl+Shift+O", self._on_import_image,
        )
        self._act_paste = add_action(
            "image", "粘贴图像", "把剪贴板里的截图直接贴进来（Ctrl+Shift+V）",
            "Ctrl+Shift+V", self._on_paste_image,
        )
        toolbar.addSeparator()

        self._act_draw = add_action("run", "计算并绘制", "按右侧条件算出相图", "Ctrl+Return",
                                    self._on_draw)
        self._act_cancel = add_action("stop", "取消", "取消当前计算", "Ctrl+C",
                                      self._on_cancel)
        self._act_cancel.setEnabled(False)
        toolbar.addSeparator()

        self._act_export = add_action("save", "导出图像…", "导出 PNG / SVG / PDF / JPG",
                                      "Ctrl+S", self._on_export)
        toolbar.addSeparator()
        self._act_reset = add_action("reset", "复位视图", "恢复初始坐标范围", "Ctrl+R",
                                     self._on_reset)
        self._act_clear = add_action("erase", "清除标注", "移除全部标注与连线", None,
                                     self._view.clear_overlays)
        self._act_log = add_action("logaxis", "对数轴", "切换 X / Y 轴对数坐标", "Ctrl+L",
                                   self._on_log_scale)
        toolbar.addSeparator()
        self._act_about = add_action("info", "交互说明", "鼠标手势与功能一览", "F1",
                                     self._on_about)

        # 到这里动作才齐活，可以安全地接线了
        self._diagram_panel.busy_changed.connect(self._act_cancel.setEnabled)

    # ---------------------------------------------------------------- 菜单
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件")
        file_menu.addAction(self._act_open)
        file_menu.addAction(self._act_import)
        file_menu.addAction(self._act_paste)
        file_menu.addSeparator()
        file_menu.addAction(self._act_export)
        file_menu.addSeparator()
        quit_act = QAction("退出", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        view = self.menuBar().addMenu("视图")
        # 关掉某个 dock 时同步取消勾选，再点一次又回来
        for label, dock, checker in (
            ("元素与相", self._left_dock, None),
            ("计算面板", self._right_dock, None),
        ):
            act = QAction(label, view)
            act.setCheckable(True)
            act.setChecked(True)

            def on_toggled(checked: bool, d: QDockWidget = dock, a: QAction = act) -> None:
                if checked:
                    a.setChecked(True)
                    self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, d)
                    d.show()
                else:
                    a.setChecked(False)
                    self.removeDockWidget(d)
                    d.hide()

            act.toggled.connect(on_toggled)
            view.addAction(act)

        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction(self._act_about)

    # ---------------------------------------------------------------- 槽
    def _on_status(self, text: str) -> None:
        # 状态栏显示的是"最后一条消息"而不是静态文案，控件树遍历（apply_to）
        # 刻意跳过 QStatusBar；翻译在这里收口。中文原文留一份，切语言时重翻。
        self._last_status = text
        self._status.showMessage(i18n.tr(text))

    def _on_draw(self) -> None:
        # 计算相图前先把中央切回画布页——否则用户还停在"导入的图像"上，
        # 算完的图看不见，会以为程序没反应
        self._stack.setCurrentWidget(self._canvas_host)
        self._diagram_panel.on_draw()

    def _on_cancel(self) -> None:
        self._diagram_panel.on_cancel()

    def _on_export(self) -> None:
        self._view.export_image(self)

    def _on_reset(self) -> None:
        self._view.reset_view()

    def _on_log_scale(self) -> None:
        self._view.toggle_log_scale()

    # ---------------------------------------------------------------- 数据库
    def _on_open_database(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("打开热力学数据库"), self._last_dir, i18n.tr(DB_FILTER)
        )
        if not path:
            return
        self._last_dir = str(Path(path).parent)
        _save_last_dir(Path(path).parent)
        self.load_database(Path(path))

    # ---------------------------------------------------------------- 图像导入
    def _on_import_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("导入相图图像"), self._last_dir, i18n.tr(IMAGE_FILTER)
        )
        if not path:
            return
        self._last_dir = str(Path(path).parent)
        self.load_image(Path(path))

    def _on_paste_image(self) -> None:
        """从剪贴板取图（截图工具 / 复制的图片都能用）。

        ``QClipboard.image()`` 在没有图像时返回**空 QImage**（不是 None），
        必须判 ``isNull()``，否则会往画布塞一张 0×0 的图，后面所有几何
        计算都会炸在除零上。
        """
        clipboard = QApplication.clipboard()
        image = clipboard.image()
        if image.isNull():
            # 有些程序（如浏览器"复制图片"）只给了文件路径，兜一下
            mime = clipboard.mimeData()
            if mime.hasUrls():
                url = mime.urls()[0]
                if url.isLocalFile():
                    self.load_image(Path(url.toLocalFile()))
                    return
            self._on_status("剪贴板里没有图像")
            return
        self.load_image(image)

    def load_image(self, source: object) -> None:
        """把图像（路径 / QImage / QPixmap / ndarray）挂到中央并切到数字化页。"""
        try:
            arr = _coerce_image_array(source)
        except (OSError, ValueError) as exc:
            i18n.warn(self, "图像导入失败", str(exc))
            return
        self._stack.setCurrentWidget(self._image_host)
        self._digitize_tab.set_image(arr)
        self._side_show(self._digitize_tab)
        self._on_status(
            f"已导入图像 {arr.shape[1]}×{arr.shape[0]}，可开始数字化（右侧「数字化相图」）"
        )

    def load_database(self, path: Path) -> None:
        """加载数据库并刷新所有依赖它的界面。"""
        try:
            database = load_database(path)
        except CalculationError as exc:
            i18n.warn(self, "数据库加载失败",
                      f"{exc.user_message}\n\n{exc.detail}")
            return

        self._database = database
        self._set_window_title()
        self._table.set_available(database.display_elements)
        self._phase_list.set_phases(database.phases)

        self._stack.setCurrentWidget(self._canvas_host)
        for idx in range(self._side_tabs.count()):
            self._side_tabs.setTabEnabled(idx, True)
        self._diagram_panel.set_enabled(True)

        # 仅二元库自动预选两个元素（开箱即可算）。多元素库（COST507 的
        # AL+B 那种）"随手挑前两个"只会留下一个用户没意识到的默认体系：
        # 他勾了 Ti/V 之后 AL 还悄悄留在计算组分里（T54 实测）。
        if len(database.display_elements) == 2:
            defaults = list(database.display_elements)
            self._table.set_selection(defaults)
        else:
            defaults = []
            self._table.clear_selection()

        self._refresh_comps_label()
        self._apply_context(defaults)
        status = (
            f"已载入 {database.name}｜元素 {len(database.display_elements)} 个｜"
            f"相 {len(database.phases)} 个｜读取 {database.load_time_s:.2f} s"
        )
        if not defaults:
            status += "｜请在周期表勾选元素后开始计算"
        self._on_status(status)
        logger.info("载入数据库 %s", database.path)

    def _apply_context(self, elements: List[str]) -> None:
        """把"当前勾选的元素"推给所有面板。

        这里**不做元素校验**：周期表允许勾选库外元素，严校验会抛
        ``CalculationError``，而这个调用在 Qt 槽里，PyQt6 对槽里的逃逸异常
        是**直接 abort 进程**；各面板内部一律用 ``comps_of`` 宽容过滤。
        """
        if self._database is None:
            return
        phases = self._phase_list.enabled_phases() or self._database.phase_names
        for tab in (
            self._diagram_panel,
            self._macro_tab,
            self._property_tab,
            self._ht_tab,
            self._scheil_tab,
            self._espei_tab,
            self._digitize_tab,
        ):
            # 任一面板内部出意外都不能拖垮整条联动链
            try:
                tab.configure(self._database, elements, phases)
            except Exception as exc:  # noqa: BLE001 - 槽函数里必须兜住
                logger.warning("面板 %s 刷新失败：%s", type(tab).__name__, exc)
        self._espei_tab.apply_settings_defaults(str(self._database.path.parent))

    def _on_espei_database_ready(self, path: str) -> None:
        """ESPEI 产物入库：直接把主窗口的数据库换成它。"""
        file_path = Path(path)
        if not file_path.is_file():
            i18n.warn(self, "数据库加载失败", f"文件不存在：{path}")
            return
        self.load_database(file_path)

    def _refresh_comps_label(self) -> List[str]:
        """刷新状态栏右侧的"体系"标签，返回**真实元素**组分（不含空位）。"""
        database = self._database
        if database is None:
            return []
        comps, ignored = database.components_safe(self._table.selection())
        if ignored:
            # 说清楚"我忽略了什么"，比静默少算一个元素安全得多
            self._on_status(
                f"已忽略 {', '.join(sorted(str(i).upper() for i in ignored))}"
                f"：不在数据库 {database.name} 中，未参与计算"
            )
        real = [c for c in comps if c != VACANCY]
        names = [e.title() for e in real]
        if not names:
            self._comps_label.setText(
                i18n.tr("体系：—（请先在周期表勾选元素）")
            )
        else:
            self._comps_label.setText(i18n.tr(f"体系：{' + '.join(names)}"))
        return real

    def _show_result_figure(self, figure, axes, caption: str) -> None:
        """属性 / ESPEI 的结果图统一画到主窗口中央画布。

        正在数字化（中央是图像画布）时不抢屏：图已挂到相图画布上，
        用户切回去就能看到。
        """
        if self._stack.currentWidget() is self._image_host:
            return
        self._stack.setCurrentWidget(self._canvas_host)
        self._view.show_external_figure(figure, axes, caption)

    # ---------------------------------------------------------------- 拖拽
    def showEvent(self, event) -> None:  # noqa: N802
        """首次显示时把左右停靠面板压到合适宽度。

        条件面板里那排"起 / 止 / 步长"输入框的 sizeHint 偏宽，不压着的话
        右侧「计算」面板能占到 400px+，把画布挤成一条。只在第一次 show
        时做一次：用户之后手动拖宽就随他。
        """
        super().showEvent(event)
        if getattr(self, "_docks_sized", False):
            return
        self._docks_sized = True
        screen = self.screen()
        screen_w = screen.availableGeometry().width() if screen is not None else 1440
        # 右侧「计算」面板≈屏宽 20%（用户反馈）：260 以下放不下输入行，420 以上太宽
        right_w = max(260, min(420, round(screen_w * 0.20)))
        self.resizeDocks(
            [self._left_dock, self._right_dock],
            [230, right_w],
            Qt.Orientation.Horizontal,
        )
        self._last_window_width = self.width()

    def resizeEvent(self, event) -> None:  # noqa: N802
        """手动缩小 / 放大窗口时，左右停靠面板按同比例缩放。

        QMainWindow 默认按固定像素保留停靠宽度：窗口从 1920 缩到 1400，
        两侧面板纹丝不动，画布被挤成一条。这里按上一次窗口宽度折算比例，
        并给左右面板与中央画布都留最小宽度；最大化 / 全屏切换不参与，
        避免和系统的窗口管理打架。
        """
        super().resizeEvent(event)
        new_w = event.size().width()
        if not getattr(self, "_docks_sized", False) or new_w <= 0:
            return
        old_w = getattr(self, "_last_window_width", 0)
        self._last_window_width = new_w
        if (old_w <= 0 or new_w >= old_w
                or self.isMaximized() or self.isFullScreen()):
            # 放大时把新增空间全部留给画布：左右面板跟着变宽只会让周期表
            # 和设置表单越拉越空。只有缩小才按比例收窄。
            return
        left_w = max(220, round(self._left_dock.width() * new_w / old_w))
        right_w = max(240, round(self._right_dock.width() * new_w / old_w))
        # 中央画布至少留 360px；不够时把两侧一起按比例压回去
        spare = new_w - left_w - right_w
        if spare < 360 and left_w + right_w > 0:
            scale = max(0.0, (new_w - 360) / (left_w + right_w))
            left_w = max(220, int(left_w * scale))
            right_w = max(240, int(right_w * scale))
        self.resizeDocks(
            [self._left_dock, self._right_dock],
            [left_w, right_w],
            Qt.Orientation.Horizontal,
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        suffix = Path(urls[0].toLocalFile()).suffix.lower() if urls else ""
        if suffix in DB_EXTS or suffix in IMAGE_EXTS:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if not urls:
            return
        path = Path(urls[0].toLocalFile())
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXTS:
            # 拖图片进来 = 导入做数字化（不需要先有数据库）
            self._last_dir = str(path.parent)
            _save_last_dir(path.parent)
            self.load_image(path)
            event.acceptProposedAction()
            return
        if suffix not in DB_EXTS:
            i18n.warn(
                self, "无法打开",
                f"只支持 .tdb / .dat 数据库文件，或图片（{', '.join(IMAGE_EXTS)}）。\n"
                f"{path.name}"
            )
            return
        self._last_dir = str(path.parent)
        _save_last_dir(path.parent)
        self.load_database(path)
        event.acceptProposedAction()

    # ---------------------------------------------------------------- 联动
    def _on_elements_changed(self, elements: List[str]) -> None:
        """元素选择变化时，三个面板都要重算组分。"""
        self._refresh_comps_label()
        self._apply_context(elements)

    def _on_phases_changed(self, _phases: List[str]) -> None:
        """相选择变化只影响计算范围，不改变组分。"""
        self._apply_context(self._table.selection())

    def _on_macro_selection(self, elements: List[str], phases: List[str]) -> None:
        """宏里的 OPEN / ELEMENTS / PHASES 反向同步到左侧面板。

        ``PeriodicTableWidget.set_selection`` 刻意不发信号（避免程序化设置
        触发一轮重算），所以这里手动刷新状态栏；相列表的 ``set_enabled``
        会发信号，由 ``_on_phases_changed`` 统一把新上下文推给各页。
        """
        self._table.set_selection(elements)
        self._refresh_comps_label()
        if phases:
            self._phase_list.set_enabled(phases)
        else:
            self._apply_context(elements)

    # ---------------------------------------------------------------- 帮助
    #: (手势, 行为) —— 交互说明对话框与模块 docstring 保持同步
    _GESTURES = (
        ("左键单击图上空白处", "就地输入并放置标注（默认带该处相名）"),
        ("拖动标注", "移动标注位置"),
        ("双击标注", "就地改名"),
        ("Shift + 左键拖动", "画 tie line（实时预览，松开落笔）"),
        ("右键单击标注 / 连线", "删除它"),
        ("右键拖动 / 中键拖动", "平移视图"),
        ("左键拖动空白", "框选缩放（虚线橡皮筋）"),
        ("滚轮", "以光标为锚缩放"),
        ("双击空白", "复位视图"),
        ("拖动图例（legend）", "把图例挪到任意位置"),
        ("周期表：Shift + 点击", "框选一段元素范围"),
    )

    def _on_about(self) -> None:
        rows = "".join(
            f"<tr><td style='padding:3px 14px 3px 0; white-space:nowrap;'>"
            f"<b>{i18n.tr(gesture)}</b></td>"
            f"<td style='padding:3px 0; color:#3a4150;'>{i18n.tr(effect)}</td></tr>"
            for gesture, effect in self._GESTURES
        )
        html = (
            f"<h3 style='margin:0 0 2px 0;'>{APP_NAME} v{APP_VERSION} 交互说明</h3>"
            "<p style='margin:4px 0 10px 0; color:#7a8494;'>"
            "所有交互都由鼠标手势直接完成，不需要切换模式。</p>"
            f"<table cellspacing='0'>{rows}</table>"
        )
        # 整段再过一遍：外面那层固定的 HTML 文案靠片段替换翻掉
        html = i18n.tr(html)
        msg = QMessageBox(self)
        msg.setWindowTitle(i18n.tr("交互说明"))
        # QMessageBox 的富文本是自动探测的：HTML 标签若不在开头，会被当成
        # 纯文本原样显示（用户实测 <b> 直接露出来）。这里显式指定。
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html)
        logo = application_icon()
        if not logo.isNull():
            msg.setIconPixmap(logo.pixmap(48, 48))
        msg.exec()
        self._on_status("已打开交互说明")


__all__ = ["MainWindow"]

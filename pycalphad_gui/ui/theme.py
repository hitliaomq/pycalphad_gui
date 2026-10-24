"""统一视觉主题：调色板、QSS 样式表、矢量图标。

对比上一版的朴素默认样式，这里做的四件事：

1. **扁平化 + 统一圆角**，去掉 Windows 原生控件的硬边框；
2. **强调色**（蓝图蓝）贯穿主按钮 / 选中态 / 进度条；
3. **矢量图标**用 QPainter 现画（不依赖 QtSvg / QtAwesome 等第三方），
   工具栏从"一排纯文字"变成"图标 + 关键项的文字"；
4. **热力图式周期表配色**改浅，避免抢相图区域的视觉重心。
"""
from __future__ import annotations

from typing import Callable, Dict, List

from PyQt6.QtCore import QPointF, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt6.QtWidgets import QApplication, QWidget

# ------------------------------------------------------------------ 调色板
PALETTE: Dict[str, str] = {
    "bg": "#f4f6f9",          # 窗口背景
    "surface": "#ffffff",     # 卡片 / 面板
    "surface_alt": "#fafbfd", # 交替行
    "border": "#e3e7ed",
    "border_soft": "#eef1f5",
    "text": "#1e2328",
    "muted": "#7a8494",
    "accent": "#2f6feb",      # 主色
    "accent_hover": "#2559c4",
    "accent_soft": "#e8f0ff",
    "danger": "#d94a3d",
    "ok": "#2ea36b",
    "warn": "#e0a020",
}

#: 应用级样式表。QSS 里不支持 CSS 变量，因此这里全是字面量；
#: 改配色只需改这一段（以及下面的周期表配色）。
APP_STYLESHEET = f"""
QWidget {{ color: {PALETTE['text']}; font-family: "Microsoft YaHei UI", "Segoe UI"; }}

QMainWindow, QDialog {{ background: {PALETTE['bg']}; }}

/* ---------- 工具栏 ---------- */
QToolBar {{
    background: {PALETTE['surface']};
    border: none;
    border-bottom: 1px solid {PALETTE['border']};
    padding: 4px 6px;
    spacing: 4px;
}}
QToolButton {{ border: none; padding: 5px 10px; border-radius: 6px; }}
QToolButton:hover {{ background: {PALETTE['accent_soft']}; }}
QToolButton:pressed {{ background: #dbe6fb; }}
QToolButton:disabled {{ color: {PALETTE['muted']}; }}

/* ---------- 停靠面板 ---------- */
QDockWidget {{ border: none; background: {PALETTE['bg']}; }}
QDockWidget::title {{
    background: {PALETTE['surface_alt']};
    border-bottom: 1px solid {PALETTE['border']};
    padding: 6px 8px;
    font-weight: 600;
    text-align: left;
}}
QDockWidget::close-button, QDockWidget::float-button {{ icon-size: 14px; }}

/* ---------- 分组框 ---------- */
QGroupBox {{
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    margin-top: 14px;
    background: {PALETTE['surface']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {PALETTE['muted']};
}}

/* ---------- 按钮 ---------- */
QPushButton {{
    background: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 7px;
    padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {PALETTE['accent']}; color: {PALETTE['accent']}; }}
QPushButton:pressed {{ background: {PALETTE['accent_soft']}; }}
QPushButton:disabled {{
    color: {PALETTE['muted']}; background: #f7f8fa; border-color: {PALETTE['border_soft']};
}}

/* 纯图标小按钮：去掉常规按钮的大内边距，否则 24px 宽的按钮字都放不下 */
QPushButton#iconBtn {{ padding: 0; font-weight: 700; }}
QPushButton#primary {{
    background: {PALETTE['accent']};
    border: 1px solid {PALETTE['accent']};
    color: white;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {PALETTE['accent_hover']}; }}
QPushButton#primary:pressed {{ background: #1e46a1; }}

/* ---------- 输入控件 ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
    background: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {PALETTE['accent']};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {PALETTE['accent']};
}}
/* 一旦用 QSS 管了数字框，步进按钮的默认箭头就没人画了（实测只剩两个
   被裁一半的碎片；改用 CSS 三角在 Windows 上也渲染成小方块——用户两次
   实测都不正常）。索性把步进按钮整体藏掉，数字框外观就是普通输入框；
   校验 / 范围钳制 / 键盘上下键微调 / 滚轮都还在，只是不画那对按钮 */
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    width: 0; height: 0; border: none; background: transparent;
}}
QComboBox::drop-down {{ border: none; width: 18px; }}

QProgressBar {{
    background: {PALETTE['border_soft']};
    border-radius: 5px;
    text-align: center;
    height: 18px;
}}
QProgressBar::chunk {{ background: {PALETTE['accent']}; border-radius: 5px; }}

/* ---------- 标签页 ---------- */
QTabWidget::pane {{
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    background: {PALETTE['surface']};
    top: -1px;
}}
QTabBar::tab {{
    background: {PALETTE['surface_alt']};
    border: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 7px 16px;
    margin-right: 2px;
    color: {PALETTE['muted']};
}}
QTabBar::tab:selected {{
    background: {PALETTE['surface']};
    color: {PALETTE['accent']};
    font-weight: 600;
    border-bottom: 2px solid {PALETTE['accent']};
}}
QTabBar::tab:!selected:hover {{ background: #f0f3f8; }}

/* ---------- 右侧「计算」面板的文档模式标签页 ---------- */
/* 全局的 pane 样式带 1px 边框 + top:-1px（普通标签页很好看），但右侧这排
   子页面是 documentMode：pane 顶边会从标签之间的缝隙里透出来，看起来像
   一条条断线（用户实测）。这里单独收掉边框、改成底部色条选中态。 */
QTabWidget#sideTabs::pane {{
    border: none;
    border-radius: 0;
    background: {PALETTE['surface']};
    top: 0;
}}
QTabWidget#sideTabs QTabBar {{ background: {PALETTE['surface']}; }}
/* 标签栏的滚动箭头是 QToolButton：全局 padding 会把它挤成空白 */
QTabBar QToolButton {{ padding: 0; min-width: 16px; }}
QTabWidget#sideTabs QTabBar::tab {{
    padding: 6px 9px;
    margin-right: 1px;
    border-radius: 0;
    border-bottom: 2px solid transparent;
    font-size: 12px;
}}
QTabWidget#sideTabs QTabBar::tab:selected {{
    background: {PALETTE['surface']};
    color: {PALETTE['accent']};
    font-weight: 600;
    border-bottom: 2px solid {PALETTE['accent']};
}}
QTabWidget#sideTabs QTabBar::tab:!selected:hover {{ background: #f0f3f8; }}

/* ---------- 其他 ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #cdd3dc; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #b4bcc9; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QStatusBar {{
    background: {PALETTE['surface']};
    border-top: 1px solid {PALETTE['border']};
    color: {PALETTE['muted']};
}}
QSplitter::handle {{ background: transparent; }}
"""

#: 周期表格子配色（浅色，不抢相图区域的视觉重心）
CELL_UNSELECTED = {"border": "#dfe4ec", "text": "#2a3038"}
SELECTED_CELL_BG = PALETTE["accent"]
SELECTED_CELL_TEXT = "#ffffff"
DISABLED_CELL_BG = "#f2f4f7"
DISABLED_CELL_TEXT = "#c2c8d2"

#: 未载入数据库时隐藏某些元素所依赖的"仅显示库内元素"开关样式
CHECKBOX_STYLE = f"""
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {PALETTE['border']}; background: white; }}
QCheckBox::indicator:checked {{ background: {PALETTE['accent']};
    border-color: {PALETTE['accent']}; }}
QCheckBox::indicator:hover {{ border-color: {PALETTE['accent']}; }}
"""


def apply_theme(app: QApplication) -> None:
    """把主题应用到整个应用。"""
    app.setStyleSheet(APP_STYLESHEET)


def apply_theme_to(widget: QWidget) -> None:
    """只给单个控件套用样式表（用于局部覆盖）。"""
    widget.setStyleSheet(APP_STYLESHEET)


# ------------------------------------------------------------------ matplotlib 字体
#: 首选中文字体列表。matplotlib 默认 DejaVu Sans 没有任何 CJK 字形，
#: 标注里写汉字会全部变成"豆腐块"，这里按可用性排一个降级序列。
CJK_FONT_CANDIDATES = [
    "Microsoft YaHei",       # Windows 现代 UI 字体
    "Microsoft YaHei UI",
    "SimHei",                # Windows 传统黑体
    "Noto Sans CJK SC",      # Linux
    "WenQuanYi Micro Hei",   # Linux
    "PingFang SC",           # macOS
    "Arial Unicode MS",
]


def apply_cjk_font() -> None:
    """让 matplotlib 能渲染中文（标注 / 图题里的汉字）。

    必须在任何 Text 对象创建之前调用 —— 字体属性是文本创建时从 rcParams
    取的，事后改 rcParams 不会刷新已存在的文本。app.main() 启动时调用一次；
    InteractiveCanvas.set_figure 里也会兜底再调一次（幂等）。
    """
    import matplotlib

    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = CJK_FONT_CANDIDATES + ["DejaVu Sans"]
    # 负号：CJK 字体里 U+2212 常缺字形，退回 ASCII 减号
    matplotlib.rcParams["axes.unicode_minus"] = False


# ------------------------------------------------------------------ 应用图标
_APP_ICON: Dict[str, QIcon] = {}


def application_icon() -> QIcon:
    """pycalphad 官方 logo（assets/pycalphad_logo.png），用作窗口 / 应用图标。

    图标缺失（例如包安装时没带 assets）时返回空图标，不影响运行。
    """
    if "app" not in _APP_ICON:
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "assets" / "pycalphad_logo.png"
        _APP_ICON["app"] = QIcon(str(path)) if path.exists() else QIcon()
    return _APP_ICON["app"]


# ------------------------------------------------------------------ 图标
_PainterCb = Callable[[QPainter, int], None]

_ICONS: Dict[str, QIcon] = {}
_ICON_SIZE = 20


def _poly(*points: float) -> QPolygonF:
    """把 (x, y, x, y, ...) 转成多边形，省得每处都敲 QPointF。"""
    return QPolygonF([QPointF(pts[0], pts[1]) for pts in zip(points[0::2], points[1::2])])


def _stroke(painter: QPainter, color: str, width: int = 2) -> None:
    # 注意 PyQt6 里 QPen 的形参顺序是 (brush, width, style, cap, join)，
    # cap 在 join 之前，写反会 TypeError。
    painter.setPen(
        QPen(QColor(color), width, Qt.PenStyle.SolidLine,
             Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    )


def _filled(painter: QPainter, color: str) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))


def _make_icons() -> None:
    """画出全部内置图标。

    坐标一律取整：PyQt6 的 ``drawLine(x1, y1, x2, y2)`` 只接受四个 ``int``，
    混进一个 ``float`` 就会 ``TypeError: arguments did not match any
    overloaded call``。20×20 的图标本来就是像素对齐的，取整无副作用。
    """
    accent = PALETTE["accent"]
    muted = PALETTE["muted"]

    def folder(p: QPainter, s: int) -> None:  # 打开数据库
        _stroke(p, accent, 2)
        p.drawRect(3, 7, s - 6, s - 11)
        p.drawLine(3, 7, 8, 3)
        p.drawLine(s - 3, 7, s - 8, 3)

    def run(p: QPainter, s: int) -> None:  # 计算并绘制
        _filled(p, accent)
        p.drawPolygon(_poly(4, 3, 4, s - 3, s - 4, s / 2))

    def stop(p: QPainter, s: int) -> None:  # 取消
        _filled(p, PALETTE["danger"])
        p.drawRoundedRect(4, 4, s - 8, s - 8, 2, 2)

    def save(p: QPainter, s: int) -> None:  # 导出图像
        _stroke(p, accent, 2)
        p.drawRect(3, 6, s - 6, s - 9)
        _filled(p, PALETTE["surface"])
        p.drawRect(5, 12, s - 10, 6)
        _filled(p, accent)
        p.drawRect(6, 13, 3, 4)

    def reset(p: QPainter, s: int) -> None:  # 复位视图
        _stroke(p, accent, 2)
        p.drawArc(3, 3, s - 6, s - 6, 30 * 16, 300 * 16)
        _filled(p, accent)
        p.drawPolygon(_poly(s - 10, 2, s - 5, 8, s - 14, 6))

    def erase(p: QPainter, s: int) -> None:  # 清除标注
        _stroke(p, accent, 2)
        p.drawLine(4, s - 5, s - 4, s - 5)
        _filled(p, accent)
        p.drawPolygon(_poly(6, s - 9, s - 6, s - 9, s - 13, 6))

    def logaxis(p: QPainter, s: int) -> None:  # 对数轴
        _stroke(p, accent, 2)
        p.drawLine(4, s - 5, s - 5, s - 5)
        p.drawLine(4, s - 5, 4, 5)
        p.drawLine(6, s - 8, s - 8, 6)
        p.drawLine(s - 8, 6, s - 8, 7)

    def exit_icon(p: QPainter, s: int) -> None:
        _stroke(p, muted, 2)
        p.drawRect(3, 6, s - 6, s - 12)
        p.drawLine(s - 9, int(s / 2), s - 3, int(s / 2))
        _filled(p, muted)
        p.drawPolygon(_poly(s - 11, 4, s - 6, int(s / 2), s - 11, s - 4))

    def info(p: QPainter, s: int) -> None:  # 关于 / 交互说明
        _stroke(p, accent, 2)
        p.drawEllipse(4, 4, s - 8, s - 8)
        _filled(p, accent)
        p.drawEllipse(int(s / 2) - 2, 8, 4, 4)
        p.drawRect(int(s / 2) - 2, 16, 4, 4)

    def image(p: QPainter, s: int) -> None:  # 导入图像（数字化相图）
        _stroke(p, accent, 2)
        p.drawRect(2, 4, s - 4, s - 8)
        _filled(p, accent)
        p.drawPolygon(_poly(4, s - 5, 9, s - 10, 14, s - 5))   # 远山
        p.drawEllipse(s - 8, 6, 4, 4)                          # 太阳

    def lang(p: QPainter, s: int) -> None:  # 切换界面语言
        _stroke(p, accent, 2)
        p.drawEllipse(3, 3, s - 6, s - 6)                       # 地球
        p.drawEllipse(int(s / 2) - 2, 3, 4, s - 6)              # 经线
        p.drawLine(3, int(s / 2), s - 3, int(s / 2))            # 赤道

    builders: List[tuple] = [
        ("open", folder), ("run", run), ("stop", stop), ("save", save),
        ("reset", reset), ("erase", erase), ("logaxis", logaxis),
        ("exit", exit_icon), ("info", info), ("image", image), ("lang", lang),
    ]
    for name, cb in builders:
        _ICONS[name] = _build_icon(cb, _ICON_SIZE)


def _build_icon(cb: _PainterCb, size: int) -> QIcon:
    """在透明画布上画一个图标。"""
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cb(painter, size)
    painter.end()
    return QIcon(pixmap)


def icon(name: str, size: int = 0) -> QIcon:
    """取内置矢量图标；名字不存在或缺 QApplication 时返回空图标。

    注意：**没有 QApplication 时不能建 QPixmap**。Qt 会直接把进程打挂
    （无 traceback、退出码非 0），try/except 根本接不住，所以这里先判实例。
    """
    if not _ICONS:
        if QApplication.instance() is None:
            return QIcon()
        try:
            _make_icons()
        except Exception:  # pragma: no cover - 图标只是装饰，失败不影响功能
            return QIcon()
    ic = _ICONS.get(name)
    if ic is None:
        return QIcon()
    if size in (0, _ICON_SIZE):
        return ic
    return QIcon(ic.pixmap(QSize(size, size)))


__all__ = [
    "PALETTE", "APP_STYLESHEET", "apply_theme", "apply_theme_to", "icon",
    "apply_cjk_font", "CJK_FONT_CANDIDATES", "application_icon",
    "SELECTED_CELL_BG", "SELECTED_CELL_TEXT",
    "DISABLED_CELL_BG", "DISABLED_CELL_TEXT", "CELL_UNSELECTED",
    "CHECKBOX_STYLE",
]

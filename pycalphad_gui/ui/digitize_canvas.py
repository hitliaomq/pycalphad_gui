"""数字化用的图像画布。

与主画布（matplotlib）分开，因为这里的操作对象是一张**位图**：

* 显示导入的相图，支持滚轮缩放 / 中键拖动平移 / 自适应窗口；
* 鼠标位置上报的是**图像像素坐标**（不是数据坐标）——数据坐标要等
  标定完成后才由 :class:`Calibration` 换算；
* 自定义光标（不靠 ``QCursor`` 那几个内置形状，因为它们画不出"过光标的
  三条 60° 直线"）：

  * 二元 → 十字光标（水平 + 垂直贯穿全图，方便对齐坐标轴）；
  * 三元 → 过光标点的三条直线，两两夹角 60°，正好与三角形三条边平行；
* 叠加层画标定点、边界点与已完成的相区多边形。

坐标换算只有两个函数 ``to_widget`` / ``to_image``，所有绘制都先转到
控件坐标再画，避免在 painter 上叠加缩放变换导致线宽跟着变。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np
import math

from PyQt6.QtCore import QPointF, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QWheelEvent,
)
from PyQt6.QtWidgets import QWidget

#: 三元光标的三条线方向（度）：两两相差 60°
TERNARY_CURSOR_ANGLES: Tuple[float, ...] = (0.0, 60.0, 120.0)

#: 叠加层配色
_COLOR_CALIB = "#2f6feb"    # 标定点：主色
_COLOR_POINT = "#d94a3d"    # 当前区域的边界点：警示红
_COLOR_REGION = "#2ea36b"   # 已完成的相区轮廓
_COLOR_GUIDE = "#8a93a3"    # 光标参考线
_FILL_ALPHA = 46             # 相区填充透明度（0~255）


def array_to_pixmap(arr: np.ndarray) -> QPixmap:
    """``uint8`` 的 ``(H, W, 3)`` RGB 数组 → ``QPixmap``。

    必须 ``.copy()``：``QImage`` 构造时只是**借用** numpy 的缓冲区，
    数组一被回收画面就花屏（Qt 文档明确要求数据在 QImage 生命周期内存活）。
    """
    from ..core.digitizer import image_to_array

    rgb = np.ascontiguousarray(image_to_array(arr))
    h, w = rgb.shape[:2]
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image)


def pixmap_to_array(pixmap: QPixmap) -> np.ndarray:
    """``QPixmap`` → ``uint8`` RGB 数组（导出与算法取用）。"""
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    w, h = image.width(), image.height()
    ptr = image.bits()
    ptr.setsize(h * w * 3)
    return np.frombuffer(ptr, dtype=np.uint8).reshape(h, w, 3).copy()


class DigitizeCanvas(QWidget):
    """显示待数字化相图的画布。"""

    #: 鼠标移动：(图像像素 x, y)；移出画布时发 (-1, -1)
    cursor_moved = pyqtSignal(float, float)
    #: 左键单击（图像像素坐标）
    clicked = pyqtSignal(float, float)
    #: 右键单击（图像像素坐标）—— 由上层决定删哪个点
    right_clicked = pyqtSignal(float, float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._scale = 1.0
        self._offset = QPointF(0.0, 0.0)
        self._hover: Optional[QPointF] = None
        self._cursor_mode = "none"          # none / cross / tri
        self._calib_points: List[Tuple[float, float]] = []
        self._boundary_points: List[Tuple[float, float]] = []
        self._regions: List[dict] = []
        self._panning = False
        self._pan_last: Optional[QPointF] = None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumHeight(200)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    # ---------------------------------------------------------------- 数据
    def set_image(self, image: object) -> None:
        """设置图像（``QPixmap`` 或 RGB 数组），并自适应窗口。"""
        if isinstance(image, QPixmap):
            self._pixmap = image
        else:
            self._pixmap = array_to_pixmap(np.asarray(image))
        self.fit_view()

    def current_array(self) -> Optional[np.ndarray]:
        """当前显示的图像（RGB 数组），供算法层使用。"""
        if self._pixmap is None:
            return None
        return pixmap_to_array(self._pixmap)

    def has_image(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    def set_cursor_mode(self, mode: str) -> None:
        """``none`` / ``cross``（二元十字）/ ``tri``（三元三线）。"""
        self._cursor_mode = mode if mode in ("none", "cross", "tri") else "none"
        self.setCursor(Qt.CursorShape.CrossCursor if self._cursor_mode != "none"
                       else Qt.CursorShape.ArrowCursor)
        self.update()

    def set_calib_points(self, points: Sequence[Tuple[float, float]]) -> None:
        self._calib_points = [(float(p[0]), float(p[1])) for p in points]
        self.update()

    def set_boundary_points(self, points: Sequence[Tuple[float, float]]) -> None:
        self._boundary_points = [(float(p[0]), float(p[1])) for p in points]
        self.update()

    def set_regions(self, regions: Sequence[dict]) -> None:
        """``regions``: ``[{"points": [(x, y), ...], "label": str}]``。"""
        self._regions = list(regions)
        self.update()

    # ---------------------------------------------------------------- 视图
    def fit_view(self) -> None:
        """缩放并居中，使整幅图刚好铺满控件。"""
        if not self.has_image():
            self.update()
            return
        img_w, img_h = self._pixmap.width(), self._pixmap.height()
        sx = max(self.width() - 8, 1) / max(img_w, 1)
        sy = max(self.height() - 8, 1) / max(img_h, 1)
        self._scale = min(sx, sy)
        self._offset = QPointF(
            (self.width() - img_w * self._scale) / 2.0,
            (self.height() - img_h * self._scale) / 2.0,
        )
        self.update()

    def reset_zoom(self) -> None:
        self.fit_view()

    def to_widget(self, px: float, py: float) -> QPointF:
        return QPointF(self._offset.x() + px * self._scale,
                       self._offset.y() + py * self._scale)

    def to_image(self, wx: float, wy: float) -> Tuple[float, float]:
        return ((wx - self._offset.x()) / self._scale,
                (wy - self._offset.y()) / self._scale)

    # ---------------------------------------------------------------- 事件
    def resizeEvent(self, event) -> None:  # noqa: N802
        # 只在"还没手动缩放过"时才重新自适应，避免拖窗口把视图拉回原点
        if not self._panning:
            self.fit_view()
        super().resizeEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if not self.has_image():
            return
        steps = event.angleDelta().y() / 120.0
        factor = 1.25 ** steps
        new_scale = min(max(self._scale * factor, 0.02), 60.0)
        factor = new_scale / self._scale
        # 以光标为锚缩放：光标下的那个像素保持不动
        pos = event.position()
        self._offset = QPointF(
            pos.x() - factor * (pos.x() - self._offset.x()),
            pos.y() - factor * (pos.y() - self._offset.y()),
        )
        self._scale = new_scale
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self.has_image():
            return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last = QPointF(event.position())
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        img_x, img_y = self.to_image(event.position().x(), event.position().y())
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(float(img_x), float(img_y))
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit(float(img_x), float(img_y))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self._pan_last = None
            self.setCursor(Qt.CursorShape.CrossCursor if self._cursor_mode != "none"
                           else Qt.CursorShape.ArrowCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self.has_image():
            return
        pos = QPointF(event.position())
        if self._panning and self._pan_last is not None:
            self._offset = QPointF(self._offset.x() + pos.x() - self._pan_last.x(),
                                   self._offset.y() + pos.y() - self._pan_last.y())
            self._pan_last = pos
            self.update()
            return
        self._hover = pos
        self.cursor_moved.emit(*self.to_image(pos.x(), pos.y()))
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = None
        self.cursor_moved.emit(-1.0, -1.0)
        self.update()

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f4f6f9"))
        if not self.has_image():
            painter.setPen(QColor("#7a8494"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "尚未导入图像\n（工具栏「导入图像」或 Ctrl+Shift+O）")
            painter.end()
            return

        # drawPixmap 的任何重载都不收 float（QPointF 的 x()/y() 也是 float），
        # 这里必须显式 int()——漏一个就是 TypeError，而且 sip 抛错后进程可能直接 abort
        px_x = int(round(self._offset.x()))
        px_y = int(round(self._offset.y()))
        px_w = int(round(self._pixmap.width() * self._scale))
        px_h = int(round(self._pixmap.height() * self._scale))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(QRect(px_x, px_y, max(px_w, 1), max(px_h, 1)),
                           self._pixmap)

        self._draw_regions(painter)
        self._draw_points(painter)
        self._draw_guides(painter)
        painter.end()

    def _draw_regions(self, painter: QPainter) -> None:
        """已完成相区的半透明填充 + 轮廓 + 标签。"""
        for region in self._regions:
            pts = [self.to_widget(x, y) for x, y in region.get("points", ())]
            if len(pts) < 2:
                continue
            painter.setPen(QPen(QColor(_COLOR_REGION), 1.6))
            painter.setBrush(QColor(46, 163, 107, _FILL_ALPHA))
            painter.drawPolygon(QPolygonF(pts + [pts[0]]))
            if region.get("label"):
                cx = sum(p.x() for p in pts) / len(pts)
                cy = sum(p.y() for p in pts) / len(pts)
                painter.setPen(QColor("#1e2328"))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawText(int(cx) - 20, int(cy), str(region["label"]))

    def _draw_points(self, painter: QPainter) -> None:
        # 当前区域的边界点（红）
        painter.setBrush(QColor(_COLOR_POINT))
        painter.setPen(QPen(QColor("#ffffff"), 1.0))
        for x, y in self._boundary_points:
            pt = self.to_widget(x, y)
            painter.drawEllipse(pt, 4.0, 4.0)

        # 标定点（蓝，带序号）
        painter.setBrush(QColor(_COLOR_CALIB))
        painter.setPen(QPen(QColor("#ffffff"), 1.2))
        for i, (x, y) in enumerate(self._calib_points):
            pt = self.to_widget(x, y)
            painter.drawEllipse(pt, 6.0, 6.0)
            painter.setPen(QColor(_COLOR_CALIB))
            painter.drawText(int(pt.x()) + 8, int(pt.y()) - 6, f"{i + 1}")
            painter.setPen(QPen(QColor("#ffffff"), 1.2))

    def _draw_guides(self, painter: QPainter) -> None:
        """自定义光标：二元十字 / 三元三线。"""
        if self._hover is None or self._cursor_mode == "none":
            return
        pen = QPen(QColor(_COLOR_GUIDE), 1.0, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        hx, hy = self._hover.x(), self._hover.y()
        if self._cursor_mode == "cross":
            painter.drawLine(0, int(hy), self.width(), int(hy))
            painter.drawLine(int(hx), 0, int(hx), self.height())
        else:
            # 三条过光标的直线，方向两两差 60°（与三角形三条边平行），
            # 长度取对角线的 2 倍，保证一定画出控件边界
            length = (self.width() + self.height()) * 2
            for deg in TERNARY_CURSOR_ANGLES:
                rad = math.radians(deg)
                dx, dy = math.cos(rad), math.sin(rad)
                painter.drawLine(
                    int(hx - dx * length), int(hy - dy * length),
                    int(hx + dx * length), int(hy + dy * length),
                )


__all__ = ["DigitizeCanvas", "array_to_pixmap", "pixmap_to_array"]

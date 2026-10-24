"""中央的相图显示区 —— 整个窗口的主角。

上一版把画布塞在「相图」标签页里，还配了一整排交互按钮；结果相图被挤在
"三个等权页签"的中间位置，既不大也不好使。这里反过来：

* **画布独占中央的绝大部分面积**（左下右侧 dock 可折叠，折叠后画布自动铺满）；
* 计算 / 进度 / 提示收进画布下方的**细条**，不抢图面的高度；
* 视图操作（复位 / 对轴 / 清除标注 / 导出）交给主工具栏，图上不再堆按钮；
* 标注一律**直接鼠标操作**（见 :mod:`pycalphad_gui.ui.interactive_canvas`）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import i18n
from ..core.exporter import export_figure
from ..core.plot_engine import PlotResult
from .interactive_canvas import InteractiveCanvas

#: 图面下方细条里的手势提示，放在这里是为了"点开就能看到"
GESTURE_HINT = (
    "左键单击加标注 · 双击标注改名 · Shift+拖动画连线 · 右键单击删除 · "
    "右键/中键拖动平移 · 左键拖动框选 · 滚轮缩放 · 双击空白复位"
)


class DiagramView(QWidget):
    """中央相图区。"""

    #: 状态栏文本
    status = pyqtSignal(str)
    #: 关于 / 交互说明
    request_help = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._result: Optional[PlotResult] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._canvas = InteractiveCanvas(self)
        self._canvas.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        self._canvas.setMinimumHeight(240)
        self._canvas.cursor_moved.connect(self._on_cursor)
        self._canvas.status_message.connect(self.status)
        layout.addWidget(self._canvas, 1)

        # ---------- 细控制条：只在需要时出现，尽量不占图面高度 ----------
        bar = QHBoxLayout()
        bar.setContentsMargins(10, 4, 10, 6)
        bar.setSpacing(6)

        self._hint = QLabel(GESTURE_HINT)
        self._hint.setWordWrap(True)  # 不换行的话最小宽度=整句宽，把窗口撑爆
        self._hint.setStyleSheet("color: #7a8494; font-size: 11px;")

        self._progress = QProgressBar(self)
        self._progress.setFixedWidth(150)
        self._progress.setValue(0)
        self._progress.hide()

        self._info = QLabel("尚未绘制")
        self._info.setWordWrap(True)
        self._info.setStyleSheet("color: #7a8494;")

        bar.addWidget(self._hint, 1)
        bar.addWidget(self._info, 0)
        bar.addWidget(self._progress)
        layout.addLayout(bar)

    # ---------------------------------------------------------------- 结果
    def set_result(self, result: PlotResult) -> None:
        """把算好的图挂到画布上。"""
        self._result = result
        self._canvas.set_figure(result.figure, [result.axes])
        self._info.setText(i18n.tr(f"耗时 {result.elapsed_s:.1f} s"))
        self.on_busy(False)

    def on_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        if busy:
            self._progress.setFormat(i18n.tr("计算中… %p%"))

    def retranslate(self) -> None:
        """切语言：翻译图上的文字并重排底部提示条。

        图面上的轴题/图例由 ``InteractiveCanvas.retranslate()`` 就地改写
        （不需要重算），底部信息条这类 QLabel 由主窗口的整树遍历兜住。
        """
        self._hint.setText(i18n.tr(GESTURE_HINT))
        self._info.setText(i18n.tr(self._info.text()))
        self.on_busy(self._progress.isVisible())
        self._canvas.retranslate()

    # ---------------------------------------------------------------- 视图操作
    def reset_view(self) -> None:
        if self._result is None:
            self.status.emit("还没有可操作的图像")
            return
        self._canvas.reset_view()

    def clear_overlays(self) -> None:
        if self._result is None:
            self.status.emit("还没有可操作的图像")
            return
        self._canvas.clear_overlays()
        self.status.emit("已清除标注")

    def toggle_log_scale(self) -> None:
        if self._result is None:
            self.status.emit("还没有可操作的图像")
            return
        self._canvas.set_log_scale("both")

    def export_image(self, parent: Optional[QWidget] = None) -> None:
        """弹导出对话框并存图。放在这里而不是工具栏，是为了复用 result 与父窗口。"""
        if self._result is None:
            self.status.emit("还没有可导出的图像")
            return
        from .export_dialog import ExportDialog

        anchor = parent if parent is not None else self
        dlg = ExportDialog(anchor, default_stem=self._result.title)
        if dlg.exec() != 1:  # QDialog.Accepted
            return
        path = dlg.selected_image_path()
        if not path:
            return
        try:
            export_figure(self._result.figure, Path(path), dpi=dlg.dpi())
        except Exception as exc:  # noqa: BLE001 - 导出失败要给可读提示，不弹堆栈
            self.status.emit(f"导出失败：{exc}")
            return
        self.status.emit(f"已导出 {path}")

    # ---------------------------------------------------------------- 提示
    def show_external_figure(self, figure, axes, caption: str) -> None:
        """显示属性页 / ESPEI 页转来的结果图（与相图共用中央画布）。

        交互（缩放 / 平移 / 标注 / 导出）对所有挂进来的图一视同仁；
        进度条复位，避免上一张相图残留的"计算中"状态。
        """
        self._canvas.set_figure(figure, axes)
        self._info.setText(caption)
        self._progress.reset()

    def set_info(self, text: str) -> None:
        self._info.setText(text)

    def notice(self, message: str, detail: str = "") -> None:
        self._info.setText(f"❌ {message}")
        self.setToolTip(detail)

    def _on_cursor(self, x: float, y: float) -> None:
        self.status.emit(f"光标：x={x:.4f}, y={y:.4f}")

    @property
    def canvas(self) -> InteractiveCanvas:
        """底层画布（供主工具栏转发视图操作）。"""
        return self._canvas


__all__ = ["DiagramView", "GESTURE_HINT"]

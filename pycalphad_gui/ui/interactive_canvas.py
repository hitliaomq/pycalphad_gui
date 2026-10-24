"""可交互的绘图画布：**纯手势驱动，没有模式按钮**。

上一版把"加标签 / 加连线"做成工具栏上的下拉框 + 两个按钮，结果用户得先切模式
再在图上点 —— 多了一步，还容易忘了切回来。这里反过来：**从鼠标动作本身推断意图**。

=====================================================  ==========================================
手势                                                  行为
=====================================================  ==========================================
左键单击图上空白处                                      就地弹出输入框，回车即放置标注（默认带上该处相名）
左键拖动标注                                            移动它
双击标注                                                就地改名
Shift + 左键拖动                                        画 tie line（实时预览，松开落笔）
右键单击标注 / 连线                                      删除它
右键拖动、中键拖动                                        平移
左键拖动空白                                             框选缩放（虚线橡皮筋）
滚轮                                                    以光标为锚缩放
双击空白                                                复位视图
=====================================================  ==========================================

「单击 → 输入框」这个设计有两个好处：一是完全不用切模式，二是默认文本已经把
标识信息带出来了（尽量取该点所在的相名），用户改一个字就行。

叠加图元都存在 ``self._labels`` / ``self._tielines`` 里，``clear_overlays``
可一键清除且不破坏底层相图数据。
"""
from __future__ import annotations

import contextlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

from matplotlib.axes import Axes
from matplotlib.backend_bases import MouseButton, MouseEvent
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.transforms import Bbox
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QLineEdit, QSizePolicy, QWidget

from ..config import ANNOTATION_BOX, TIELINE_COLOR
from .. import i18n
from ..i18n import apply_to_figure

#: 小于这个位移（像素）就视为"点击"而不是"拖动"
CLICK_SLOP_PX = 4
#: 框选缩放的最小像素边长
MIN_ZOOM_PX = 8
#: 命中标注 / 连线时的宽容度（像素）
HIT_TOL_PX = 3


def shift_pressed(event: MouseEvent) -> bool:
    """判断事件是否带 Shift。

    matplotlib 3.9 之后 ``MouseEvent`` 不再有 ``.shift`` 属性，改为
    ``modifiers``（字符串集合）；3.8 及更早是 ``.shift`` 布尔值。这里两个都兼容，
    否则在 3.11 上按下鼠标就会 ``AttributeError``。
    """
    modifiers = getattr(event, "modifiers", None)
    if modifiers is not None:
        return "shift" in modifiers
    return bool(getattr(event, "shift", False))


def _distance_to_segment(px: float, py: float,
                         p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """点到线段的距离（二平面几何，用于连线命中判定）。"""
    (x1, y1), (x2, y2) = p1, p2
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    return (((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5)


@contextlib.contextmanager
def _frozen_autoscale(ax: Any):
    """临时冻结坐标轴自动缩放，防止叠加层偷改坐标范围。

    ``ax.plot()`` 在 autoscale 打开时会顺手 ``relim()``，matplotlib 再给数据
    范围加 5% 边距 —— 结果就是"画一条 tie line，整张相图被悄悄放大"。
    标注 / tie line / 预览线只是叠在已有图上的用户注记，绝不该动坐标轴。
    """
    x_on, y_on = ax.get_autoscalex_on(), ax.get_autoscaley_on()
    if x_on:
        ax.set_autoscalex_on(False)
    if y_on:
        ax.set_autoscaley_on(False)
    try:
        yield
    finally:
        if x_on:
            ax.set_autoscalex_on(True)
        if y_on:
            ax.set_autoscaley_on(True)


class InteractiveCanvas(QWidget):
    """承载 matplotlib 图表并提供叠加交互的控件。"""

    #: 鼠标在数据坐标下移动时发出 (x, y)
    cursor_moved = pyqtSignal(float, float)
    #: 状态栏提示
    status_message = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._figure: Optional[Figure] = None
        self._axes: List[Axes] = []
        #: 挂载时各坐标轴的初始范围快照，"复位视图"直接恢复它
        self._initial_limits: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        self._labels: List = []
        self._tielines: List[Line2D] = []

        # --- 手势状态 ---
        self._press: Optional[Dict[str, Any]] = None     # 按下时的快照
        self._moved_px: int = 0                          # 本次按下累计位移
        self._drag_index: Optional[int] = None           # 正在拖动的标注序号
        self._pan_last: Optional[Tuple[float, float]] = None
        self._preview: Optional[Line2D] = None           # tie line 预览线
        self._band: Optional[Rectangle] = None           # 框选橡皮筋

        # --- 就地编辑 ---
        self._editor: Optional[QLineEdit] = None
        self._editing: Optional[Any] = None
        self._editing_new: bool = False
        self._editing_text: str = ""

        self._set_cursor(Qt.CursorShape.OpenHandCursor)
        self.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )

    # ---------------------------------------------------------------- 挂载
    def set_figure(self, figure: Figure, axes: Sequence[Axes]) -> None:
        """把引擎产出的 Figure 挂载到控件上。"""
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

        self._close_editor(commit=False)
        self.clear_overlays()

        if getattr(self, "_canvas", None) is not None:
            self._layout_remove()

        self._figure = figure
        self._axes = list(axes)
        self._initial_limits = []  # 换图时重置快照，避免混入旧图的范围
        # 接管后坐标轴范围归我们说了算：交还给 autoscale 的话，标注 / tie line
        # 会触发 relim()+autoscale_view()，用户随手画一笔，整张图就被放大一点。
        # （_unstale() 会在任何一次 transform 失效重算时偷偷跑 relim。）
        for a in self._axes:
            try:
                a.set_autoscale_on(False)
            except Exception:  # pragma: no cover - 老版本 matplotlib 没这个 API
                pass
            # 记下初始范围：autoscale 已关，"复位视图"只能靠这份快照
            self._initial_limits.append((tuple(a.get_xlim()), tuple(a.get_ylim())))
            # 图例可拖动：用户要求图例能挪位置。set_draggable 是 Legend 自带能力。
            legend = a.get_legend()
            if legend is not None:
                try:
                    legend.set_draggable(True)
                except Exception:  # pragma: no cover - 极老版本没有该 API
                    pass
        # 兜底再调一次（幂等）：测试等场景绕过了 app.main()，字体没机会设置
        from .theme import apply_cjk_font

        apply_cjk_font()
        # 引擎在后台线程用 Agg 造好的 Figure，在这里换上真正的 Qt 画布。
        # FigureCanvasQTAgg 的构造会顺带 figure.set_canvas()，把后台的 Agg 画布顶掉，
        # 之后的交互与绘制就都发生在主线程了。
        self._canvas = FigureCanvasQTAgg(figure)
        self._canvas.setParent(self)
        self._canvas.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        layout = self._ensure_layout()
        layout.addWidget(self._canvas)

        self._canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._connect_events()
        self._canvas.updateGeometry()
        # 引擎的轴题/标题/图例是后台线程按**源码语言**写好的（"温度 T (K)"、
        # "（无有限值）"），挂上画布后立刻就地翻一遍——只翻词典里有的文本，
        # 刻度数字、相名、用户标注一律不动（幂等，重复调用安全）
        apply_to_figure(self._figure)
        self._canvas.draw_idle()
        self._set_cursor(Qt.CursorShape.OpenHandCursor)

    def clear_figure(self) -> None:
        """卸载当前图，回到空画布状态。

        ``set_figure`` 不接受 ``None``（它要拿 figure 去构造 ``FigureCanvasQTAgg``），
        所以"切库后清屏"得走这条路——否则面板会一直挂着上一轮的图。
        """
        self._close_editor(commit=False)
        self.clear_overlays()
        self._layout_remove()
        self._figure = None
        self._axes = []
        self._initial_limits = []

    def _ensure_layout(self):
        from PyQt6.QtWidgets import QVBoxLayout

        if self.layout() is None:
            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            self.setLayout(layout)
        return self.layout()

    def _layout_remove(self) -> None:
        old = getattr(self, "_canvas", None)
        if old is not None:
            self.layout().removeWidget(old)
            old.setParent(None)
            old.deleteLater()

    def _set_cursor(self, shape: Qt.CursorShape) -> None:
        canvas = getattr(self, "_canvas", None)
        if canvas is not None:
            canvas.setCursor(shape)

    def _connect_events(self) -> None:
        # matplotlib 没有 ``dblclick_event`` 这个信号，双击只能靠
        # ``button_press_event`` 上的 ``event.dblclick`` 标志分辨（见 _on_press）。
        self._cid_press = self._canvas.mpl_connect("button_press_event", self._on_press)
        self._cid_move = self._canvas.mpl_connect("motion_notify_event", self._on_move)
        self._cid_release = self._canvas.mpl_connect("button_release_event", self._on_release)
        self._cid_pick = self._canvas.mpl_connect("pick_event", self._on_pick)

    # ---------------------------------------------------------------- 工具
    def _active_axes(self) -> Optional[Axes]:
        return self._axes[0] if self._axes else None

    @staticmethod
    def _is_triangular(ax: Optional[Axes]) -> bool:
        """三元三角投影下平移 / 缩放语义不明，交由专门分支处理。"""
        return bool(ax is not None and getattr(ax, "name", "") == "triangular")

    def _label_index_under(self, event: MouseEvent) -> Optional[int]:
        """返回光标下的标注序号。

        不用 ``Annotation.contains``：matplotlib 的 Text.contains 会把事件坐标从
        显示坐标换到"文本所在变换"下再比较，实际使用中命中率很不稳定（实测在
        数据坐标锚点上仍返回 False）。这里直接拿 ``get_window_extent()`` 的显示
        矩形做判定，行为确定、好测。
        """
        for i, annot in reversed(list(enumerate(self._labels))):
            try:
                box: Bbox = annot.get_window_extent()
            except Exception:  # pragma: no cover - 未渲染时可能拿不到
                continue
            if (box.x0 - HIT_TOL_PX <= event.x <= box.x1 + HIT_TOL_PX
                    and box.y0 - HIT_TOL_PX <= event.y <= box.y1 + HIT_TOL_PX):
                return i
        return None

    def _tieline_index_under(self, event: MouseEvent) -> Optional[int]:
        """返回光标下的 tie line 序号（点到线段距离）。"""
        ax = self._active_axes()
        if ax is None:
            return None
        for i, line in reversed(list(enumerate(self._tielines))):
            xdata, ydata = line.get_data()
            if len(xdata) < 2:
                continue
            (x0, y0), (x1, y1) = ax.transData.transform((xdata[0], ydata[0])), \
                ax.transData.transform((xdata[-1], ydata[-1]))
            if _distance_to_segment(event.x, event.y, (x0, y0), (x1, y1)) <= HIT_TOL_PX + 2:
                return i
        return None

    # ---------------------------------------------------------------- 事件
    def _on_press(self, event: MouseEvent) -> None:
        ax = self._active_axes()
        if ax is None or event.inaxes is None:
            return

        # 每次按下都先清掉上一次手势的残留状态：_drag_index 若不清理，
        # "拖完一个标注再在空白处拖动"会把这个旧标注拽着跑（实测 bug）。
        self._drag_index = None

        self._press = {
            "btn": event.button,
            "x": event.xdata,
            "y": event.ydata,
            "px": event.x,
            "py": event.y,
            "shift": shift_pressed(event),
        }
        self._moved_px = 0

        if event.dblclick:
            self._on_double_click(event)
            # 双击的 release 不能再按"单击"处理，否则双击空白会先复位视图、
            # 又在原地新建一个标注（两段按下各自生成一次 click）。
            self._press = None
            return

        button = event.button
        if button == MouseButton.LEFT:
            idx = self._label_index_under(event)
            if idx is not None:
                # 抓住已有标注：抬高 zorder，拖动时不会被遮挡
                self._labels[idx].set_zorder(20)
                self._drag_index = idx
                self._set_cursor(Qt.CursorShape.ClosedHandCursor)
            elif shift_pressed(event):
                self._start_tieline_preview()
        elif button in (MouseButton.RIGHT, MouseButton.MIDDLE):
            if not self._is_triangular(ax):
                self._pan_last = (event.xdata, event.ydata)
                self._set_cursor(Qt.CursorShape.ClosedHandCursor)

    def _on_move(self, event: MouseEvent) -> None:
        press = self._press
        ax = self._active_axes()
        if ax is None:
            return
        if event.xdata is not None and event.ydata is not None:
            self.cursor_moved.emit(float(event.xdata), float(event.ydata))
        if press is None or press["x"] is None or event.x is None or event.y is None:
            return

        self._moved_px = max(
            self._moved_px,
            abs(event.x - press["px"]) + abs(event.y - press["py"]),
        )
        dragged = self._moved_px > CLICK_SLOP_PX

        # 1) 拖动标注
        if self._drag_index is not None and self._drag_index < len(self._labels):
            if event.xdata is not None and event.ydata is not None:
                annot = self._labels[self._drag_index]
                annot.xy = (event.xdata, event.ydata)
                if annot.xyann is not None:
                    annot.xyann = (event.xdata, event.ydata)
                self._canvas.draw_idle()
            return

        # 2) 平移（右键 / 中键）
        if self._pan_last is not None and event.xdata is not None and event.ydata is not None:
            if self._is_triangular(ax):
                return
            x0, y0 = self._pan_last
            if None in (x0, y0):
                return
            ax.set_xlim(left=ax.get_xlim()[0] - (event.xdata - x0),
                        right=ax.get_xlim()[1] - (event.xdata - x0))
            ax.set_ylim(bottom=ax.get_ylim()[0] - (event.ydata - y0),
                        top=ax.get_ylim()[1] - (event.ydata - y0))
            self._pan_last = (event.xdata, event.ydata)
            self._canvas.draw_idle()
            return

        if not dragged:
            return

        # 3) Shift + 拖动：tie line 预览
        if press["shift"] and event.xdata is not None and event.ydata is not None:
            self._update_tieline_preview(press["x"], press["y"], event.xdata, event.ydata)
            return

        # 4) 左键拖动空白：框选橡皮筋
        if press["btn"] == MouseButton.LEFT and event.xdata is not None and event.ydata is not None:
            self._update_band(press["x"], press["y"], event.xdata, event.ydata)

    def _on_release(self, event: MouseEvent) -> None:
        press = self._press
        ax = self._active_axes()
        self._press = None
        self._pan_last = None
        self._set_cursor(Qt.CursorShape.OpenHandCursor)

        if press is None or ax is None or event.inaxes is None:
            return
        dragged = self._moved_px > CLICK_SLOP_PX

        if dragged:
            # Shift 拖动 → 落笔一条 tie line
            if press["shift"] and event.xdata is not None and event.ydata is not None:
                self._commit_tieline(press["x"], press["y"], event.xdata, event.ydata)
            # 左键拖动 → 框选缩放
            elif press["btn"] == MouseButton.LEFT:
                self._apply_band_zoom()
            self._hide_band()
            self._hide_tieline_preview()
            self._drag_index = None
            return

        # 没拖动，那就是一次"点击"
        if press["btn"] == MouseButton.LEFT:
            if self._drag_index is None and event.xdata is not None and event.ydata is not None:
                self._add_label_interactively(event.xdata, event.ydata)
        elif press["btn"] == MouseButton.RIGHT:
            self._remove_under_cursor(event)

        self._drag_index = None

    def _on_double_click(self, event: MouseEvent) -> None:
        """双击标注就地改名；双击空白复位视图。"""
        idx = self._label_index_under(event)
        if idx is not None and idx < len(self._labels):
            self._open_editor(self._labels[idx], self._labels[idx].get_text())
            return
        # 双击的第一击会在空白处新建标注（就地编辑框可能还开着）。
        # 用户意图是"复位视图"，不是"放一个标注再复位"——若编辑中的是
        # 这次双击刚带出来的新标注，就地放弃它。
        if self._editing_new:
            self._close_editor(commit=False)
        self.reset_view()
        self.status_message.emit("已复位视图")

    def _on_pick(self, event) -> None:  # noqa: ANN001 - mpl 回调签名
        """点中连线 = 删除（配合右键单击同样可以删除，这里是兜底）。"""
        artist = event.artist
        for i, line in enumerate(self._tielines):
            if artist is line:
                line.remove()
                self._tielines.pop(i)
                self._canvas.draw_idle()
                self.status_message.emit("已删除 tie line")

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt 命名约定
        """以光标位置为锚点做缩放。"""
        ax = self._active_axes()
        canvas = getattr(self, "_canvas", None)
        if ax is None or canvas is None:
            super().wheelEvent(event)
            return

        # canvas 铺满本控件，故控件坐标即画布像素坐标
        rect = canvas.rect()
        xt = event.position().x() - rect.x()
        yt = event.position().y() - rect.y()
        inv = ax.transData.inverted()
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15

        try:
            x0, x1 = ax.get_xlim()
            y0, y1 = ax.get_ylim()
            cx, cy = inv.transform((xt, yt))
            new_x = (x0 - (cx - x0) * factor, x1 + (cx - x1) * factor)
            new_y = (y0 - (cy - y0) * factor, y1 + (cy - y1) * factor)
            if not self._is_triangular(ax):
                ax.set_xlim(new_x)
                ax.set_ylim(new_y)
            else:
                # 三角投影：等比缩放保持三角形形状
                mid = (x0 + x1) / 2
                half = (x1 - x0) / 2 * factor
                ax.set_xlim(mid - half, mid + half)
                ax.set_ylim(y0, y1)
            canvas.draw_idle()
        except Exception:  # pragma: no cover - 极端缩放下数值退化
            pass
        event.accept()

    # ---------------------------------------------------------------- 标注
    def _add_label_interactively(self, x: float, y: float) -> None:
        """单击建标注：先建好、立刻就地改名，编辑框取消则撤掉。"""
        # 默认名也要过一遍词典：不然英文模式下点出来的新标注还叫"标注 1"
        default = self._phase_name_at(x, y) or i18n.tr(
            f"标注 {len(self._labels) + 1}"
        )
        annot = self.add_label(default, x, y, silent=True)
        if annot is None:
            return
        self._open_editor(annot, default, is_new=True)

    def _phase_name_at(self, x: float, y: float) -> Optional[str]:
        """尽力取回光标处所在的相名：二元 ZPFE 用 PolyCollection 填色。"""
        ax = self._active_axes()
        if ax is None:
            return None
        try:
            for coll in list(ax.collections) + list(ax.patches):
                label = coll.get_label()
                if not label or label.startswith("_"):
                    continue
                point = (x, y)
                if hasattr(coll, "contains_point"):
                    if coll.contains_point(point):
                        return str(label)
                if hasattr(coll, "get_paths"):
                    for path in coll.get_paths():
                        if path.contains_point(point):
                            return str(label)
        except Exception:  # pragma: no cover - 命中检测失效不应影响主流程
            return None
        return None

    def add_label(self, text: str, x: float, y: float, silent: bool = False) -> Optional[Any]:
        """在数据坐标 (x, y) 处放置一个可拖动的标注。"""
        ax = self._active_axes()
        if ax is None:
            return None
        with _frozen_autoscale(ax):
            annot = ax.annotate(
                text,
                xy=(x, y),
                xytext=(x, y),
                textcoords="data",
                ha="center",
                va="center",
                fontsize=9,
                # boxstyle 只存在于 bbox 字典里，直接当关键字传会报
                # "'Annotation' object has no property 'boxstyle'"
                bbox=ANNOTATION_BOX,
            )
        # matplotlib 的 Artist 上没有 set_pickable()，设 picker 即可拾取
        annot.set_picker(True)
        annot.set_zorder(20)
        self._labels.append(annot)
        self._canvas.draw_idle()
        if not silent:
            self.status_message.emit(f"已添加标注「{text}」")
        return annot

    def add_tieline(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> None:
        """在两点之间画一条 tie line。"""
        ax = self._active_axes()
        if ax is None:
            return
        (x1, y1), (x2, y2) = p1, p2
        with _frozen_autoscale(ax):
            line, = ax.plot([x1, x2], [y1, y2], color=TIELINE_COLOR, lw=1.6,
                            zorder=6, picker=True)
        self._tielines.append(line)
        self._canvas.draw_idle()
        self.status_message.emit("已添加 tie line")

    # --- 就地编辑 ---
    def _open_editor(self, annot: Any, text: str, is_new: bool = False) -> None:
        self._close_editor(commit=False)
        editor = self._editor
        if editor is None:
            editor = QLineEdit(self)
            editor.setObjectName("labelEditor")
            editor.setFixedWidth(150)
            editor.returnPressed.connect(lambda: self._close_editor(commit=True))
            editor.editingFinished.connect(lambda: self._close_editor(commit=True))
            self._editor = editor
        self._editing = annot
        self._editing_new = is_new
        self._editing_text = annot.get_text()
        editor.blockSignals(True)
        editor.setText(text)
        editor.selectAll()
        editor.blockSignals(False)
        editor.show()
        editor.raise_()
        editor.setFocus()
        pos = self._annot_to_widget(annot)
        editor.move(pos - QPoint(0, editor.height()))

    def _close_editor(self, commit: bool = True) -> None:
        """收起编辑框。``commit`` 为真时把文本写回标注。"""
        editor = self._editor
        annot = self._editing
        # 先把标志存下来再清状态：下面的"放弃新建标注"分支要用它
        is_new = self._editing_new
        self._editing = None
        self._editing_new = False
        if editor is None or annot is None:
            if editor is not None:
                editor.hide()
            return

        editor.blockSignals(True)
        editor.hide()
        editor.blockSignals(False)

        text = editor.text().strip()
        if commit and text:
            annot.set_text(text)
            self._canvas.draw_idle()
            self.status_message.emit(f"标注「{text}」已就位")
        elif is_new:
            # 放弃新标注（空文本也算放弃）
            self._remove_annot(annot)

    def _remove_annot(self, annot: Any) -> None:
        if annot in self._labels:
            self._labels.remove(annot)
        try:
            annot.remove()
        except Exception:  # pragma: no cover
            pass
        self._canvas.draw_idle()

    def _annot_to_widget(self, annot: Any) -> QPoint:
        """把标注的数据坐标换算到本控件的像素坐标，用于摆放编辑框。"""
        canvas = getattr(self, "_canvas", None)
        ax = self._active_axes()
        if canvas is None or ax is None:
            return QPoint(0, 0)
        try:
            dx, dy = ax.transData.transform(annot.xy)
            return canvas.mapTo(self, QPoint(int(dx), int(dy)))
        except Exception:  # pragma: no cover
            return QPoint(0, 0)

    # ---------------------------------------------------------------- 删除
    def _remove_under_cursor(self, event: MouseEvent) -> None:
        idx = self._label_index_under(event)
        if idx is not None and idx < len(self._labels):
            self._remove_annot(self._labels[idx])
            self.status_message.emit("已删除标注")
            return
        tl_idx = self._tieline_index_under(event)
        if tl_idx is not None and tl_idx < len(self._tielines):
            self._tielines[tl_idx].remove()
            self._tielines.pop(tl_idx)
            self._canvas.draw_idle()
            self.status_message.emit("已删除 tie line")

    # ---------------------------------------------------------------- 框选缩放
    def _update_band(self, x0: float, y0: float, x1: float, y1: float) -> None:
        ax = self._active_axes()
        if ax is None:
            return
        if self._band is None:
            self._band = Rectangle(
                (x0, y0), abs(x1 - x0), abs(y1 - y0),
                transform=ax.transData,
                facecolor="#2f6feb", alpha=0.12, edgecolor="#2f6feb",
                linestyle="--", lw=1.2, fill=True, visible=False, zorder=30,
            )
            ax.add_patch(self._band)
        self._band.set_xy((min(x0, x1), min(y0, y1)))
        self._band.set_width(abs(x1 - x0))
        self._band.set_height(abs(y1 - y0))
        self._band.set_visible(True)
        self._canvas.draw_idle()

    def _hide_band(self) -> None:
        if self._band is not None:
            try:
                self._band.set_visible(False)
                self._band.remove()
            except Exception:  # pragma: no cover
                pass
            self._band = None

    def _apply_band_zoom(self) -> None:
        """按橡皮筋矩形缩放。像素太小（误点）或三元投影下都不做。"""
        ax = self._active_axes()
        canvas = getattr(self, "_canvas", None)
        if ax is None or canvas is None or self._band is None:
            return
        if self._is_triangular(ax):
            self.status_message.emit("三元三角投影不支持框选缩放")
            return
        x0, y0 = self._band.get_xy()
        x1, y1 = x0 + self._band.get_width(), y0 + self._band.get_height()
        if x1 <= x0 or y1 <= y0:
            return
        # 最小尺寸必须用**显示像素**比较：MIN_ZOOM_PX 是像素阈值，
        # 数据坐标的量纲随轴范围变化（成分轴 0~1、温度轴 300~1500），
        # 直接比数据宽度会导致成分轴上框选永远不生效（实测 bug）。
        (dx0, dy0), (dx1, dy1) = ax.transData.transform((x0, y0)), ax.transData.transform((x1, y1))
        if abs(dx1 - dx0) < MIN_ZOOM_PX or abs(dy1 - dy0) < MIN_ZOOM_PX:
            return
        ax.set_xlim(min(x0, x1), max(x0, x1))
        ax.set_ylim(min(y0, y1), max(y0, y1))
        canvas.draw_idle()

    # ---------------------------------------------------------------- tie line 预览
    def _start_tieline_preview(self) -> None:
        ax = self._active_axes()
        if ax is None or self._preview is not None:
            return
        with _frozen_autoscale(ax):
            self._preview, = ax.plot(
                [], [], color=TIELINE_COLOR, lw=1.6, ls="--", alpha=0.75, zorder=25
            )

    def _update_tieline_preview(self, x0: float, y0: float, x1: float, y1: float) -> None:
        if self._preview is None:
            self._start_tieline_preview()
        if self._preview is None:
            return
        self._preview.set_data([x0, x1], [y0, y1])
        self._canvas.draw_idle()

    def _hide_tieline_preview(self) -> None:
        if self._preview is not None:
            try:
                self._preview.remove()
            except Exception:  # pragma: no cover
                pass
            self._preview = None

    def _commit_tieline(self, x0: float, y0: float, x1: float, y1: float) -> None:
        if None in (x0, y0, x1, y1):
            return
        self.add_tieline((x0, y0), (x1, y1))

    # ---------------------------------------------------------------- 坐标控制
    def set_axis_limits(self, xlim: Optional[Tuple[float, float]] = None,
                        ylim: Optional[Tuple[float, float]] = None) -> None:
        """按数据坐标设置坐标轴范围。"""
        ax = self._active_axes()
        if ax is None:
            return
        if xlim is not None and ax.name != "triangular":
            ax.set_xlim(*xlim)
        if ylim is not None and ax.name != "triangular":
            ax.set_ylim(*ylim)
        self._canvas.draw_idle()

    def retranslate(self) -> int:
        """切语言时翻译图上已有的文字（轴题 / 图例 / 标题 / 刻度）。

        matplotlib 的 ``Text`` 不是 QWidget，控件树遍历扫不到；这里单独走一遍，
        只翻词典里有的文本——相名、数值、用户自己写的标注都原样保留。
        """
        if self._figure is None:
            return 0
        n = apply_to_figure(self._figure)
        if n:
            self._canvas.draw_idle()
        return n

    def set_log_scale(self, which: str = "both") -> None:
        """切换对数坐标；三角投影不适用。"""
        ax = self._active_axes()
        if ax is None or ax.name == "triangular":
            self.status_message.emit("三元三角投影不支持对数坐标")
            return
        if which in ("x", "both"):
            ax.set_xscale("log" if ax.get_xscale() == "linear" else "linear")
        if which in ("y", "both"):
            ax.set_yscale("log" if ax.get_yscale() == "linear" else "linear")
        self._canvas.draw_idle()

    def reset_view(self) -> None:
        """恢复挂载时快照的初始坐标范围。

        旧实现 ``relim() + autoscale_view()`` 有两个问题：

        * :meth:`set_figure` 已把 autoscale 关掉（防止叠加层偷改范围），
          ``autoscale_view()`` 对关闭的轴是**空操作** —— 所以工具栏的
          "复位视图"点了毫无反应；
        * ``relim()`` 会把 tie line 等叠加层也算进数据范围，越复位越歪。

        因此直接恢复 :meth:`set_figure` 里记录的初始范围才是真"复位"。
        """
        if not self._axes:
            return
        for ax, (xlim, ylim) in zip(self._axes, self._initial_limits):
            ax.set_xlim(*xlim)
            ax.set_ylim(*ylim)
        self._canvas.draw_idle()

    def clear_overlays(self) -> None:
        """清除全部标注与连线，不影响底层相图。"""
        for annot in list(self._labels):
            try:
                annot.remove()
            except Exception:  # pragma: no cover
                pass
        for line in list(self._tielines):
            try:
                line.remove()
            except Exception:  # pragma: no cover
                pass
        self._labels.clear()
        self._tielines.clear()
        self._drag_index = None
        self._hide_band()
        self._hide_tieline_preview()
        # 移除 artist 只是改了场景，不重绘的话屏幕上依旧显示旧帧，
        # 看起来就像"清除标注"点了没效果 —— 这里必须补一次重绘。
        canvas = getattr(self, "_canvas", None)
        if canvas is not None:
            canvas.draw_idle()

    @property
    def overlays(self) -> Dict[str, list]:
        return {"labels": self._labels, "tielines": self._tielines}

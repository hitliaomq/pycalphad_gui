"""离屏 GUI 冒烟测试。

不打开可见窗口，用 ``QT_QPA_PLATFORM=offscreen`` 构造真实控件树并驱动一遍
主流程：载入数据库 → 周期表/相列表刷新 → 排除相 → 后台线程画一张小网格
二元图 → 交互层加标签 → 导出 PNG。

目的是拦住"语法能过、一构造就崩"这类问题（Qt 构造期异常只有真跑一遍才暴露）。
需要本机有 PyQt6；缺库时本模块整体跳过。
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from PyQt6.QtGui import QAction  # QAction 在 QtGui 而不是 QtWidgets
from PyQt6.QtWidgets import QComboBox, QStackedWidget

if not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pycalphad_gui import i18n  # noqa: E402  必须在 sys.path 补好之后

DB_DIR = Path(
    r"C:/Users/liaom/AppData/Local/Programs/Python/Python312"
    r"/Lib/site-packages/pycalphad/tests/databases"
)
BIN_DB = DB_DIR / "alzn_mey.tdb"
#: V–Zr 用户实测用库（复现"属性不出图"的真实数据），随仓库携带
VZR_DB = ROOT / "tests" / "databases" / "vzr_zha-2012.tdb"

try:  # pragma: no cover - 环境差异
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

results: list = []


def check(name: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    else:
        results.append((name, True, ""))
        print(f"ok   {name}")


def test_window_constructs() -> None:
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    assert win.windowTitle(), "窗口标题不应为空"


def test_load_database_refreshes_ui() -> None:
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(BIN_DB)

    table = win._table
    # 周期表按钮的键是规范写法（Al/Zn），与 TDB 里的 ZN/AL 大小写不同，比大小写
    enabled = {sym.upper() for sym, btn in table._buttons.items() if btn.isEnabled()}
    assert "ZN" in enabled, f"周期表应点亮 ZN，实际 {enabled}"
    assert table.selection(), "默认应已选中若干元素"
    # 新语义：所有元素常显，库内高亮 / 库外灰化但不禁用；VA 与 /- 在第 1 行空白格
    assert all(btn.isEnabled() for btn in table._buttons.values()), "库外元素只灰化，不禁用"
    for sym in ("VA", "/-"):
        assert sym in table._buttons, f"凹位应存在伪元素 {sym}"
        assert table._buttons[sym].isEnabled(), f"{sym} 应可点击"
    assert "/-" in enabled, "/- 应作为伪元素格常驻凹位"

    phases = win._phase_list.enabled_phases()
    assert phases, "相列表应有默认启用的相"

    assert win._comps_label.text().strip(), "体系标签不应为空"
    assert "LIQUID" in " ".join(phases), f"默认应启用 LIQUID，实际 {phases}"


def test_empty_state_before_load() -> None:
    """启动后、载入数据库之前：引导卡可见、三个功能页禁用。

    这条锁的是"运行 app.py 后在界面里选择导入数据库"这条路径的前半段 ——
    少了守卫，用户第一时间点到「相图」页会得到一个点不动也看不懂的界面。
    """
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.show()

    assert win._empty.isVisible(), "未载入数据库时应显示引导卡"
    assert not win._comps_label.text(), "未载入时状态栏不应显示体系"
    assert not win._database, "启动后不应自带数据库"

    # 「数字化相图」与「宏命令」不依赖数据库：前者导入外部图，后者自带 OPEN
    always = {
        win._side_index(win._digitize_tab),
        win._side_index(win._macro_tab),
    }
    for idx in range(win._side_tabs.count()):
        if idx in always:
            assert win._side_tabs.isTabEnabled(idx), f"第 {idx} 页应始终可用"
            continue
        assert not win._side_tabs.isTabEnabled(idx), f"未载入时第 {idx} 页应禁用"

    # 相图必须是主角：中央是画布（引导卡只是占位），左右各一个停靠面板
    stack = win.centralWidget()
    assert isinstance(stack, QStackedWidget), type(stack).__name__
    assert stack.currentWidget() is win._empty, "未载入数据库时应停在引导卡"
    assert stack.count() == 3, "中央区应有「引导卡 / 画布 / 导入的图像」三页"
    assert win._left_dock is not None and win._right_dock is not None

    # 工具栏上必须能直接找到打开入口，不能只有菜单里藏着
    from pycalphad_gui import i18n
    actions = [a.text() for a in win.findChildren(QAction) if a.text()]
    assert i18n.tr("打开数据库…") in actions, f"工具栏/菜单缺少打开入口：{actions}"


def test_empty_state_cleared_after_load() -> None:
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.show()  # 必须先显示，否则子控件的 isVisible() 恒为 False
    win.load_database(BIN_DB)

    assert not win._empty.isVisible(), "载入后引导卡应隐藏"
    assert win._comps_label.text(), "载入后状态栏应显示体系"
    for idx in range(win._side_tabs.count()):
        assert win._side_tabs.isTabEnabled(idx), f"载入后第 {idx} 页应可用"


def test_exclude_phase() -> None:
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(BIN_DB)
    win._phase_list.set_enabled(["LIQUID"])  # type: ignore[attr-defined]
    phases = win._phase_list.enabled_phases()
    assert phases == ["LIQUID"], f"排除后只剩 LIQUID，实际 {phases}"
    # 相变化要能传导到相图页
    assert win._diagram_panel._phases == ["LIQUID"], win._diagram_panel._phases


def test_default_sweep_is_usable() -> None:
    """默认条件面板应直接给出「温度 + 首个元素」这组可算条件。"""
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(BIN_DB)
    panel = win._diagram_panel
    sweeps = panel.sweeps()
    assert "T" in sweeps, f"默认应有温度扫描，实际 {sweeps}"
    comps = [k for k in sweeps if k not in ("T", "P", "N")]
    assert comps, f"默认应有组分扫描，实际 {sweeps}"


def test_plot_small_binary() -> None:
    """真跑一次后台计算：小网格二元 ZPFE，验证线程 + 画布链路。"""
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(BIN_DB)

    panel = win._diagram_panel
    rows = panel._panel._rows  # 扫描条件的行控件（ConditionPanel 内部）
    # 收紧网格，把 12 s 的计算压到几秒
    rows[0].set_target("T")
    rows[0].start.setValue(600.0)
    rows[0].stop.setValue(900.0)
    rows[0].step.setValue(100.0)
    rows[1].set_target("ZN")
    rows[1].start.setValue(0.0)
    rows[1].stop.setValue(1.0)
    rows[1].step.setValue(0.25)
    if len(rows) > 2:
        for row in list(rows)[2:]:
            panel._panel._remove_row(row)

    done = []
    errors = []

    def on_success(result) -> None:
        done.append(result)

    def on_failed(message, detail) -> None:
        errors.append(f"{message} — {detail}")

    # 拦截渲染，避免真的占用画布；失败路径也要接住，否则只会看到"超时"而看不到原因
    panel._on_success = on_success
    panel._on_failed = on_failed
    panel.on_draw()

    deadline = time.time() + 180.0
    while time.time() < deadline and not done:
        QApplication.processEvents()
        time.sleep(0.05)

    assert done or errors, (
        "二元相图应在超时前出结果；若没有，说明后台线程没跑起来。" + (f"失败原因：{errors[0]}" if errors else "")
    )
    assert not errors, f"二元相图不应失败：{errors[0]}"
    result = done[0]
    assert result.figure is not None, "应产出 figure"
    assert result.axes is not None, "应产出坐标区"


def test_canvas_attached_on_main_thread() -> None:
    """后台线程只产出 Agg Figure，Qt 画布必须等到主线程 set_figure 才创建。

    这条锁死的是"线程 + Qt"这条红线：若 Figure 是在 QtAgg 后端下于工作线程里
    创建的，就等于跨线程 new 了 QWindow，Windows 上会间歇性崩溃。
    """
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    from pycalphad_gui.ui.interactive_canvas import InteractiveCanvas

    fig = Figure()  # Agg 后端：内部画布是 Agg，不是 Qt
    fig.add_subplot(111)
    assert not isinstance(fig.canvas, FigureCanvasQTAgg), "Agg 后端下不应生成 Qt 画布"

    holder = InteractiveCanvas()
    holder.set_figure(fig, fig.axes)
    assert holder._canvas is fig.canvas, "set_figure 应接管 figure 的画布"
    assert isinstance(
        fig.canvas, FigureCanvasQTAgg
    ), "set_figure 之后 figure 上挂的必须是 Qt 画布"


def _gesture_harness() -> tuple:
    """搭一个带 Qt 画布的空图，供手势测试用。"""
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure

    from pycalphad_gui.ui.interactive_canvas import InteractiveCanvas

    fig = Figure(figsize=(6, 4), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([0, 1], [0, 1])
    fig.set_canvas(FigureCanvasQTAgg(fig))
    holder = InteractiveCanvas()
    holder.set_figure(fig, [ax])
    return fig, ax, holder


def _make_event(fig, ax, name: str, x: float, y: float, button=1, modifiers=None,
                dblclick: bool = False):
    """造一个已经處理过的 matplotlib 鼠标事件（inaxes / 数据坐标都已填好）。"""
    from matplotlib.backend_bases import MouseEvent

    event = MouseEvent(
        name, fig.canvas, x=x, y=y, button=button,
        dblclick=dblclick, modifiers=modifiers or frozenset(),
    )
    event._process()
    return event


def test_label_and_tieline_interaction() -> None:
    """加标签 / 加 tie line / 清除叠加图元。"""
    from pycalphad_gui.ui.interactive_canvas import InteractiveCanvas

    fig, ax, holder = _gesture_harness()

    holder.add_label("FCC_A1", 0.3, 0.3)
    holder.add_label("HCP_A3", 0.7, 0.7)
    holder.add_tieline((0.2, 0.2), (0.8, 0.8))
    overlays = holder.overlays
    assert len(overlays["labels"]) == 2, overlays
    assert len(overlays["tielines"]) == 1, overlays

    holder.clear_overlays()
    assert not holder.overlays["labels"], "清除后不应残留标签"
    assert not holder.overlays["tielines"], "清除后不应残留连线"


def table_module():
    """导入 periodic_table 模块，供修饰键桩件替换用。"""
    from pycalphad_gui.ui import periodic_table

    return periodic_table


def test_click_places_label_with_inline_editor() -> None:
    """**左键单击**图面即放置标注，并就地弹出编辑框（不需要切模式）。

    这是用户明确点名要的交互：图上直接鼠标搞定，下方不再有"标签模式"按钮。
    """
    from PyQt6.QtWidgets import QLineEdit

    from pycalphad_gui.ui.interactive_canvas import InteractiveCanvas

    fig, ax, holder = _gesture_harness()
    px, py = ax.transData.transform((0.4, 0.4))

    press = _make_event(fig, ax, "button_press_event", px, py, button=1)
    release = _make_event(fig, ax, "button_release_event", px, py, button=1)
    fig.canvas.callbacks.process("button_press_event", press)
    fig.canvas.callbacks.process("button_release_event", release)

    assert holder.overlays["labels"], "单击应放置一个标注"
    editor = holder.findChild(QLineEdit)
    # 注意：本测试没有真正 show 窗口，isVisible() 恒 False，只能查 isHidden()
    assert editor is not None and not editor.isHidden(), "应就地弹出编辑框"
    assert editor.text(), "编辑框应带默认文本"

    # 回车提交后，标注文本应变成输入内容
    editor.setText("LIQUID")
    holder._close_editor(commit=True)
    annot = holder.overlays["labels"][0]
    assert annot.get_text() == "LIQUID", annot.get_text()
    assert editor.isHidden(), "提交后编辑框应隐藏"

    # 放弃编辑：新建的标注应被撤掉
    px2, py2 = ax.transData.transform((0.8, 0.8))
    press2 = _make_event(fig, ax, "button_press_event", px2, py2, button=1)
    release2 = _make_event(fig, ax, "button_release_event", px2, py2, button=1)
    fig.canvas.callbacks.process("button_press_event", press2)
    fig.canvas.callbacks.process("button_release_event", release2)
    before = len(holder.overlays["labels"])
    holder._close_editor(commit=False)
    assert len(holder.overlays["labels"]) == before - 1, "取消编辑应撤掉新建的标注"


def test_shift_drag_creates_tieline() -> None:
    """**Shift + 左键拖动**画 tie line：按下 → 移动 → 松开。"""
    from pycalphad_gui.ui.interactive_canvas import InteractiveCanvas

    fig, ax, holder = _gesture_harness()
    x0, y0 = ax.transData.transform((0.2, 0.3))
    x1, y1 = ax.transData.transform((0.7, 0.8))
    mods = frozenset({"shift"})

    fig.canvas.callbacks.process(
        "button_press_event",
        _make_event(fig, ax, "button_press_event", x0, y0, button=1, modifiers=mods))
    fig.canvas.callbacks.process(
        "motion_notify_event",
        _make_event(fig, ax, "motion_notify_event", (x0 + x1) / 2, (y0 + y1) / 2,
                    button=None, modifiers=mods))
    fig.canvas.callbacks.process(
        "button_release_event",
        _make_event(fig, ax, "button_release_event", x1, y1, button=1, modifiers=mods))

    assert len(holder.overlays["tielines"]) == 1, "Shift 拖动应画出一条 tie line"
    xdata, _ = holder.overlays["tielines"][0].get_data()
    # 合成事件的像素坐标会被量化，容差 0.02
    assert abs(xdata[0] - 0.2) < 0.02 and abs(xdata[-1] - 0.7) < 0.02, xdata


def test_right_click_deletes_under_cursor() -> None:
    """**右键单击**删除光标下的标注 / 连线。"""
    from pycalphad_gui.ui.interactive_canvas import InteractiveCanvas

    fig, ax, holder = _gesture_harness()
    holder.add_label("FCC_A1", 0.3, 0.3)
    holder.add_tieline((0.2, 0.2), (0.8, 0.8))

    px, py = ax.transData.transform((0.3, 0.3))
    fig.canvas.callbacks.process(
        "button_press_event", _make_event(fig, ax, "button_press_event", px, py, button=3))
    fig.canvas.callbacks.process(
        "button_release_event", _make_event(fig, ax, "button_release_event", px, py, button=3))
    assert len(holder.overlays["labels"]) == 0, "右键单击应删掉标注"

    # 连线：取线段中点
    lx, ly = ax.transData.transform((0.5, 0.5))
    fig.canvas.callbacks.process(
        "button_press_event", _make_event(fig, ax, "button_press_event", lx, ly, button=3))
    fig.canvas.callbacks.process(
        "button_release_event", _make_event(fig, ax, "button_release_event", lx, ly, button=3))
    assert len(holder.overlays["tielines"]) == 0, "右键单击应删掉连线"


def test_label_drag_does_not_leak_state() -> None:
    """拖动一次标注后，再在空白处左键拖动应做框选缩放（而不是拽着旧标注跑）。

    对应用户实测 bug：_drag_index 在 release 后不清零，导致后续手势错乱。
    """
    fig, ax, holder = _gesture_harness()
    holder.add_label("FCC_A1", 0.5, 0.5)
    lx, ly = ax.transData.transform((0.5, 0.5))

    # 第一段手势：按住标注拖到 (0.3, 0.3)
    fig.canvas.callbacks.process(
        "button_press_event", _make_event(fig, ax, "button_press_event", lx, ly, button=1))
    mx, my = ax.transData.transform((0.3, 0.3))
    fig.canvas.callbacks.process(
        "motion_notify_event", _make_event(fig, ax, "motion_notify_event", mx, my, button=None))
    fig.canvas.callbacks.process(
        "button_release_event", _make_event(fig, ax, "button_release_event", mx, my, button=1))

    annot = holder.overlays["labels"][0]
    assert abs(annot.xy[0] - 0.3) < 0.03, annot.xy

    # 第二段手势：在空白处 (0.7, 0.2) → (0.9, 0.4) 左键拖动
    xlim0, ylim0 = ax.get_xlim(), ax.get_ylim()
    px, py = ax.transData.transform((0.7, 0.2))
    qx, qy = ax.transData.transform((0.9, 0.4))
    fig.canvas.callbacks.process(
        "button_press_event", _make_event(fig, ax, "button_press_event", px, py, button=1))
    fig.canvas.callbacks.process(
        "motion_notify_event", _make_event(fig, ax, "motion_notify_event", qx, qy, button=None))
    fig.canvas.callbacks.process(
        "button_release_event", _make_event(fig, ax, "button_release_event", qx, qy, button=1))

    assert abs(annot.xy[0] - 0.3) < 0.05, f"旧标注不应被拽走：{annot.xy}"
    assert ax.get_xlim() != xlim0 or ax.get_ylim() != ylim0, "空白拖动应是框选缩放"


def test_state_sweep_row_is_editable() -> None:
    """二元相图要扫温度：T 行的起止步长输入框不能被禁用。"""
    from pycalphad_gui.ui.condition_panel import SweepRow

    row = SweepRow(["T", "ZN"])
    row.set_target("T")
    for box in (row.start, row.stop, row.step):
        assert box.isEnabled(), "温度扫描的输入框必须可编辑（二元相图要扫 T）"
    row.start.setValue(500.0)
    row.stop.setValue(1200.0)
    row.step.setValue(25.0)
    assert row.as_triple() == (500.0, 1200.0, 25.0), row.as_triple()


def test_legend_is_draggable_after_set_figure() -> None:
    """引擎画出的 legend 挂到画布后应可拖动。"""
    from matplotlib.figure import Figure

    from pycalphad_gui.ui.interactive_canvas import InteractiveCanvas

    fig = Figure(figsize=(6, 4), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([0, 1], [0, 1], label="LIQUID")
    ax.legend(loc="best")
    holder = InteractiveCanvas()
    holder.set_figure(fig, [ax])
    legend = ax.get_legend()
    assert legend is not None
    assert legend.get_draggable(), "legend 应可拖动"


def test_reset_view_restores_initial_limits() -> None:
    """**复位视图**应恢复挂载时的初始范围。

    autoscale 在挂载时已被关闭（防叠加层偷改范围），旧实现的
    ``relim()+autoscale_view()`` 因此成了空操作 —— 工具栏点了没反应。
    """
    from pycalphad_gui.ui.interactive_canvas import InteractiveCanvas

    fig, ax, holder = _gesture_harness()
    initial = (tuple(ax.get_xlim()), tuple(ax.get_ylim()))

    ax.set_xlim(0.2, 0.4)
    ax.set_ylim(0.3, 0.6)
    holder.add_tieline((0.25, 0.35), (0.35, 0.45))
    holder.reset_view()

    assert tuple(ax.get_xlim()) == initial[0], (ax.get_xlim(), initial)
    assert tuple(ax.get_ylim()) == initial[1], (ax.get_ylim(), initial)


def test_pseudo_cells_sit_in_top_row() -> None:
    """VA 与 /- 应位于第 1 周期第 7、8 列（用户红框指定的位置）。"""
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    for sym, (row, col) in (("VA", (1, 7)), ("/-", (1, 8))):
        btn = win._table._buttons[sym]
        grid = btn.parent().layout()
        pos = grid.getItemPosition(grid.indexOf(btn))
        assert pos[:2] == (row, col), f"{sym} 应在 ({row},{col})，实际 {pos[:2]}"


def test_cycle_clicks_never_touch_missing_api() -> None:
    """周期表单击 / Shift+点击都不应抛 AttributeError。

    ``buttonClicked`` 发出的是 ``QAbstractButton``，它没有 ``modifiers()``
    （那是 QMouseEvent 的），一旦按压下去就整条链路崩掉，用户表现为"点一下
    元素就报那个 traceback"。这里把两条分支都跑一遍。
    """
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    table = win._table
    # 按钮键是表格里的原始符号（混小写），不是大写
    fe, zn, mn = table._buttons["Fe"], table._buttons["Zn"], table._buttons["Mn"]

    # 普通点击（Qt 会先把按钮勾上，再发 buttonClicked）
    fe.setChecked(True)
    table._on_button_clicked(fe)
    # 选中集统一存大写（T54）：按钮符号是 'Fe'，存进去是 'FE'
    assert "FE" in set(table.selection()), table.selection()

    # Shift+点击（框选区间）
    class _ShiftedApp:
        @staticmethod
        def keyboardModifiers():  # noqa: N802 - 保持 Qt 风格命名
            return Qt.KeyboardModifier.ShiftModifier

    module = table_module()
    real_app = module.QApplication
    try:
        module.QApplication = _ShiftedApp  # type: ignore[assignment]
        zn.setChecked(True)
        table._on_button_clicked(zn)
    finally:
        module.QApplication = real_app  # type: ignore[assignment]

    selected = set(table.selection())
    # Fe(26) → Zn(30) 整段都应被框上：Co/Ni/Cu 是区间内的中间元素。
    # 之前 SYMBOL_TO_Z[first.upper()] 对"Fe"/"Zn" 查不到 → KeyError 被
    # except 吞掉，整段框选静默失效。选中集统一大写（T54）。
    assert {"FE", "CO", "NI", "CU", "ZN"} <= selected, selected


def test_periodic_table_fits_without_scroll() -> None:
    """滚动区最小高度要装下整张周期表，不滚鼠标就能看到镧系 / 锕系。"""
    from pycalphad_gui.ui.main_window import MainWindow
    from pycalphad_gui.ui.periodic_table import CELL_H

    win = MainWindow()
    scroller = win._table._scroller
    # 9 行内容（主表 7 行 + 镧系 + 锕系）× 行高 + 行距与余量
    assert scroller.minimumHeight() >= CELL_H * 9 + 10, scroller.minimumHeight()


def test_no_mode_selector_in_view() -> None:
    """主窗口里不该再出现"模式下拉框"这类按钮式交互。"""
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(BIN_DB)

    texts = " ".join(
        a.text() for a in win.findChildren(QAction) if a.text()
    )
    for combo in win.findChildren(QComboBox):
        joined = " ".join(
            (combo.itemText(i) for i in range(combo.count()))
        )
        word = "标签" if i18n.lang() == "zh" else "label"
        assert word not in joined.lower(), f"图形交互不该再是下拉框：{joined}"

    # 工具栏上应有一个"交互说明"，把鼠标手势讲清楚
    assert i18n.tr("交互说明") in texts, texts


def test_view_toolbar_actions_exist() -> None:
    """工具栏的视图动作必须都在（空图时点它们也只给提示，不崩）。"""
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(BIN_DB)
    for name in ("_act_reset", "_act_clear", "_act_log", "_act_export", "_act_draw"):
        assert getattr(win, name) is not None, f"工具栏缺少 {name}"


def test_export_from_gui() -> None:
    from pycalphad_gui.core.exporter import export_figure
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(BIN_DB)
    panel = win._diagram_panel
    rows = panel._panel._rows
    rows[0].set_target("T")
    rows[0].start.setValue(600.0)
    rows[0].stop.setValue(700.0)
    rows[0].step.setValue(100.0)
    rows[1].set_target("ZN")
    rows[1].start.setValue(0.0)
    rows[1].stop.setValue(1.0)
    rows[1].step.setValue(0.5)

    holder = []
    errors = []

    def on_success(result) -> None:
        holder.append(result)

    panel._on_success = on_success
    panel._on_failed = lambda m, d: errors.append(f"{m} — {d}")
    panel.on_draw()

    deadline = time.time() + 180.0
    while time.time() < deadline and not holder:
        QApplication.processEvents()
        time.sleep(0.05)

    assert holder, "导出用例的前置计算应完成"
    out = Path(tempfile.mkdtemp()) / "gui.png"
    export_figure(holder[0].figure, out)
    assert out.exists() and out.stat().st_size > 0


def test_property_tab_fixed_inputs_follow_scan_axis() -> None:
    """扫温度要"固定组分"、扫组分要"固定温度"，两者不能同时可用。

    属性页过去把固定温度硬编码在引擎里，用户改了 spinbox 也不生效；扫温度时
    又没给组分条件，pycalphad 直接抛"自由度为不为零"——图自然出不来。
    """
    from pycalphad_gui.core.database_manager import load_database
    from pycalphad_gui.ui.property_tab import PropertyTab

    db = load_database(BIN_DB)
    tab = PropertyTab()
    tab.configure(db, ["ZN", "AL"], db.phase_names)

    assert tab._xvar.count() > 1, "扫描轴下拉应含 T 与各组分"
    assert tab._xvar.currentText() == "T"
    tab.add_fixed_comp_row("ZN", 0.5)
    assert tab._fixed_comps() == {"ZN": 0.5}, "扫温度时应能添加固定成分行"
    assert not tab._fixedT.isEnabled(), "扫温度时固定温度输入应禁用"

    tab._xvar.setCurrentText("ZN")
    assert tab._fixedT.isEnabled(), "扫组分时固定温度输入应可用"
    # 扫组分时固定成分行不再参与条件（引擎自动跳过），但仍可增删管理
    assert tab._fixed_comps() == {"ZN": 0.5}


def test_property_tab_end_to_end_visible_curve() -> None:
    """属性页真跑一遍：曲线必须"看得见"，进度条必须推满。

    T46：plot() 的 autoscale 是**挂起请求**，首次绘制才真正套用；而画布挂载时
    会先关掉 autoscale，请求就被作废——viewLim 停在默认 (0,1)，图例在、线却
    画在视野外（用户实测"进度条卡 66% 且不出图"）。引擎必须在交付前把范围落定。
    """
    import numpy as np

    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(VZR_DB)
    table = win._table
    for sym in ("V", "ZR"):
        btn = table._buttons.get(sym)
        if btn is not None:
            btn.setChecked(True)
            table._on_button_clicked(btn)

    ptab = win._property_tab
    ptab._xvar.setCurrentText("V")
    ptab._xstep.setValue(0.05)
    ptab._fixedT.setValue(600.0)
    ptab._on_run()

    deadline = time.time() + 120.0
    while time.time() < deadline and ptab._btn_run.isEnabled() is False:
        QApplication.processEvents()
        time.sleep(0.05)
    assert ptab._btn_run.isEnabled(), "属性计算应在超时前完成"

    assert "❌" not in ptab._info.text(), f"属性计算失败：{ptab._info.text()}"
    assert ptab._progress.value() == ptab._progress.maximum(), (
        f"成功后进度条应推满，实际 {ptab._progress.value()}/{ptab._progress.maximum()}"
    )

    result = ptab._result
    assert result is not None and result.series, "应产出曲线"
    ys = np.concatenate([y for _, y in result.series.values()])
    assert np.isfinite(ys).any(), "曲线数据不应全为 NaN"

    # 属性图现在画在主窗口中央画布（与相图共用），不再挤在右侧小面板里
    assert win._stack.currentWidget() is win._canvas_host, "属性结果应切到中央画布"
    ax = win._view._canvas._axes[0]
    ymin, ymax = ax.get_ylim()
    assert ymin <= ys.min() + 1e-6 and ymax >= ys.max() - 1e-6, (
        f"视野 {ymin:.4g}~{ymax:.4g} 未覆盖数据 "
        f"{ys.min():.4g}~{ys.max():.4g}（挂起 autoscale 被作废，T46）"
    )


def test_ht_tab_nphases_column_is_filled() -> None:
    """高通量表格的"共存相数"必须先有列、再有数字（T49）。

    用户实测：勾了"共存相数"，表头在，单元格却全空。原因在两处叠加——
    core 交付的 int 经 DataFrame.iat 读回是 ``np.int64``（不是 Python int 的
    子类），界面 ``isinstance(x, (int, float, str))`` 把它判成"不可显示"清成
    空串；同时勾"液相分数"时 ``eq.coords["Phase"]`` 在这类库上是 ``KeyError``。
    这里走真实 UI 路径，断言表格里真能读到数字。
    """
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(VZR_DB)
    tab = win._ht_tab
    # 全勾：五个指标一起跑，顺带覆盖 np_liquid 的 KeyError 路径
    for cb in tab._outputs.values():
        cb.setChecked(True)

    tab._panel._rows[0].set_target("T")
    tab._panel._rows[0].start.setValue(1000.0)
    tab._panel._rows[0].stop.setValue(1100.0)
    tab._panel._rows[0].step.setValue(100.0)
    if len(tab._panel._rows) > 1:
        tab._panel._rows[1].set_target("V")
        tab._panel._rows[1].start.setValue(0.5)
        tab._panel._rows[1].stop.setValue(0.6)
        tab._panel._rows[1].step.setValue(0.1)

    tab._on_run()
    deadline = time.time() + 180.0
    while time.time() < deadline and tab._btn_run.isEnabled() is False:
        QApplication.processEvents()
        time.sleep(0.05)
    assert tab._btn_run.isEnabled(), "高通量扫描应在超时前完成"

    headers = [tab._table.horizontalHeaderItem(c).text() for c in range(tab._table.columnCount())]
    # 表头是"显示文案"（随语言翻译），列的归属要从 DataFrame 列名认
    n_phase_col = i18n.tr("共存相数")
    assert n_phase_col in headers, f"表格缺少共存相数列，实际表头：{headers}"

    col = headers.index(n_phase_col)
    texts = []
    for r in range(tab._table.rowCount()):
        item = tab._table.item(r, col)
        assert item is not None, f"共存相数第 {r} 行为空单元格"
        texts.append(item.text())
    assert texts and all(t.strip().lstrip("-").isdigit() for t in texts), (
        f"共存相数单元格文本应是有数字，实际 {texts}"
    )
    # 相数必须落在合理区间（这个库一共就 4 个相，不可能冒出两位数）
    n_phases = [int(t) for t in texts]
    assert all(1 <= n <= 4 for n in n_phases), f"共存相数越界：{n_phases}"
    assert tab._table.rowCount() > 0


def test_selected_elements_limit_panel_candidates() -> None:
    """T52：多元素库里只勾 Ti / V，各面板就不该再出现库内其他元素。

    用户实测（cost507R，库里 20 个元素）：勾选 Ti、V 之后，属性页的扫描轴
    与 Scheil 的组分输入行仍然摆着 AL、CU、MG… —— 勾选形同虚设，用户以为
    算的是 Ti–V，其实随时可能被扫到别的元素。
    """
    from dataclasses import replace

    from pycalphad_gui.core.database_manager import load_database
    from pycalphad_gui.ui.diagram_panel import DiagramPanel
    from pycalphad_gui.ui.property_tab import PropertyTab
    from pycalphad_gui.ui.scheil_tab import ScheilTab

    base = load_database(VZR_DB)  # 真库只有 V / ZR 两个
    # 伪造成 COST507 那种多元素库：只改元数据，相模型不动
    multi = replace(
        base,
        display_elements=("AL", "CU", "MG", "TI", "V", "ZR"),
        all_elements=("AL", "CU", "MG", "TI", "VA", "V", "ZR"),
    )
    phases = multi.phase_names
    picked = ["TI", "V"]

    ptab = PropertyTab(None)
    ptab.configure(multi, picked, phases)
    xvar = [ptab._xvar.itemText(i) for i in range(ptab._xvar.count())]
    assert xvar == ["T", "TI", "V"], f"属性页扫描轴应只含勾选元素，实际 {xvar}"

    stab = ScheilTab(None)
    stab.configure(multi, picked, phases)
    assert sorted(stab._comp_widgets) == ["TI", "V"], (
        f"Scheil 组分行应只给勾选元素，实际 {sorted(stab._comp_widgets)}"
    )

    panel = DiagramPanel(None)
    panel.configure(multi, picked, phases)
    # T55：状态变量只给 T，P/N 不再作为扫描维度候选
    assert panel._panel._targets == ["TI", "V", "T"], panel._panel._targets
    assert panel._comps == ["TI", "V", "VA"], panel._comps


def test_add_sweep_row_button_does_not_crash() -> None:
    """T56：点"添加扫描维度"不能 abort（PyQt6 clicked 信号带 bool 参数）。

    add_btn.clicked 直接绑 add_row 时，clicked 的 checked 参数（False/True）
    被当成 target 传进去，set_target(True).strip() 抛 AttributeError——
    而且**逃逸出槽的异常在 PyQt6 里是 abort 进程**，不是打日志。
    """
    from PyQt6.QtWidgets import QPushButton

    from pycalphad_gui.ui.condition_panel import ConditionPanel

    panel = ConditionPanel(show_diagram_type=False, show_plot_options=False)
    panel.set_target_candidates(["TI", "V"])
    n0 = len(panel._rows)
    btn = next(w for w in panel.findChildren(QPushButton) if "添加" in w.text())
    btn.click()  # 走真实 clicked 信号路径，带 bool 参数
    assert len(panel._rows) == n0 + 1
    assert panel._rows[-1].target() == "TI", "新行应默认选首个组分"
    btn.click(); btn.click()
    assert len(panel._rows) == n0 + 3
    # P/N 不应出现在任何一行的候选里（T55）
    row = panel._rows[-1]
    items = [row.var.itemText(i) for i in range(row.var.count())]
    assert "P" not in items and "N" not in items, items


def test_ternary_style_options_exposed() -> None:
    """三元线式/填色开关要经 plot_options 传到引擎。

    默认映射线式（grid_fill=False），勾选后走官网 plot_shaded_ternary
    填色样式（映射未收敛时退网格法填色）；tielines 开关控制 tie line。
    """
    from pycalphad_gui.ui.condition_panel import ConditionPanel

    panel = ConditionPanel(show_diagram_type=False)
    opts = panel.plot_options()
    assert opts["tielines"] is True
    assert opts["label_nodes"] is False
    assert opts["grid_fill"] is False
    panel._opt_fill.setChecked(True)
    assert panel.plot_options()["grid_fill"] is True


def test_out_of_database_element_does_not_break_linkage() -> None:
    """勾了库外元素不能把主窗口联动链打断（T52 的连带修复）。

    周期表允许勾选库外元素（灰显但仍可点），原先下游 ``components_for`` 会
    抛 ``CalculationError``；而这个调用在 Qt 槽里，PyQt6 对槽里逃逸的异常是
    **直接 abort 进程**（不是打日志），用户表现为"点一下元素整个软件没了"。
    """
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(VZR_DB)

    win._table.set_selection(["V", "ZR"])
    win._on_elements_changed(["V", "ZR"])
    assert win._diagram_panel._comps == ["V", "ZR", "VA"]

    # 混进一个库外元素（AU 不在 V-Zr 库里）
    win._table.set_selection(["V", "ZR", "AU"])
    win._on_elements_changed(["V", "ZR", "AU"])  # 不该抛

    assert win._diagram_panel._comps == ["V", "ZR", "VA"], win._diagram_panel._comps
    xvar = [win._property_tab._xvar.itemText(i) for i in range(win._property_tab._xvar.count())]
    assert xvar == ["T", "V", "ZR"], f"库外元素不应进扫描轴候选，实际 {xvar}"
    assert "AU" not in win._diagram_panel._panel._targets

    # 状态栏要如实说"我忽略了谁"，而不是默默少算
    label = win._comps_label.text()
    assert "V" in label and "Zr" in label, f"体系标签未反映真实组分：{label}"


def test_set_selection_checks_buttons_case_insensitive() -> None:
    """T54 根因：按钮符号是 ``Al``/``Ti`` 混合大小写，选中集是大写。

    以前 ``symbol in self._selected`` 永远比不中两字母元素——**AL 留在
    选中集里、按钮却不点亮**。用户看到的是"我只勾了 Ti、V"，状态栏和
    各面板候选里却一直有 Al（COST507 实测截图）。
    """
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(BIN_DB)  # alzn_mey：预选 AL + ZN，两个都是两字母
    table = win._table

    assert table._buttons["Al"].isChecked(), "预选的 Al 按钮必须点亮"
    assert table._buttons["Zn"].isChecked(), "预选的 Zn 按钮必须点亮"
    assert table.selection() == ["AL", "ZN"]

    # 用户点掉 Zn、换选别的：选中集与按钮必须始终同步
    table.set_selection(["AL"])
    assert not table._buttons["Zn"].isChecked()
    assert table.selection() == ["AL"]
    assert i18n.tr("未勾选") not in table._summary.text(), table._summary.text()


def test_multi_element_database_starts_without_selection() -> None:
    """T54：多元素库不该偷偷预选前两个元素。

    COST507（20 元素）一载入就预选 AL+B——用户勾选 Ti/V 后 AL 仍悄悄留在
    计算组分里。二元库保留预选（开箱即可算），多元素库一律从空选开始。
    """
    import pycalphad_gui.ui.main_window as mw_module
    from dataclasses import replace

    from pycalphad_gui.core.database_manager import load_database

    base = load_database(VZR_DB)
    multi = replace(
        base,
        display_elements=("AL", "CU", "MG", "TI", "V", "ZR"),
        all_elements=("AL", "CU", "MG", "TI", "VA", "V", "ZR"),
    )
    original = mw_module.load_database
    mw_module.load_database = lambda path: multi
    try:
        win = mw_module.MainWindow()
        win.load_database(VZR_DB)
    finally:
        mw_module.load_database = original

    assert win._table.selection() == [], "多元素库载入后不应预选任何元素"
    assert win._table._buttons["Al"].isChecked() is False
    assert win._diagram_panel._comps == [], "空选时不能拿 [VA] 空壳当组分"
    assert i18n.tr("未勾选") in win._table._summary.text()

    # 二元库仍保留预选
    win2 = mw_module.MainWindow()
    win2.load_database(VZR_DB)  # V–Zr 二元
    assert win2._table.selection() == ["V", "ZR"]


def test_property_tab_per_phase_default() -> None:
    """属性页默认就该给逐相曲线，且每相一条、互不雷同（T50）。"""
    import numpy as np

    from pycalphad_gui.config import PROPERTY_SCOPES
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.load_database(VZR_DB)
    table = win._table
    for sym in ("V", "ZR"):
        btn = table._buttons.get(sym)
        if btn is not None:
            btn.setChecked(True)
            table._on_button_clicked(btn)

    ptab = win._property_tab
    assert ptab._scope.currentIndex() == PROPERTY_SCOPES.index("per_phase"), (
        "默认曲线来源应是逐相——用户就是因为默认只给平衡态才提的反馈"
    )

    # 在相列表里只留两个相，顺带验证勾选过滤真的传到引擎
    ptab._set_all_phases(False)
    kept = [ptab._phase_list.item(0).text(), ptab._phase_list.item(1).text()]
    for name in kept:
        for i in range(ptab._phase_list.count()):
            if ptab._phase_list.item(i).text() == name:
                ptab._phase_list.item(i).setCheckState(Qt.CheckState.Checked)
    # 扫温度：起/止/步长这一行必须真的是温度范围（T50 附带修复）
    assert ptab._xstart.value() == 300.0 and ptab._xstop.value() == 1500.0, (
        "切到扫温度后，起止值应自动变成温度范围而非组分的 0→1"
    )
    ptab._xstart.setValue(500.0)
    ptab._xstop.setValue(1500.0)
    ptab._xstep.setValue(100.0)
    ptab.add_fixed_comp_row("AL", 0.5)  # 扫温度：钉一个固定成分
    ptab._on_run()

    deadline = time.time() + 180.0
    while time.time() < deadline and ptab._btn_run.isEnabled() is False:
        QApplication.processEvents()
        time.sleep(0.05)
    assert ptab._btn_run.isEnabled(), "属性计算应在超时前完成"

    result = ptab._result
    assert result is not None, f"属性计算没出结果：{ptab._info.text()}"
    assert sorted(result.series) == sorted(kept), f"应只画勾选的两个相，实际 {list(result.series)}"
    ymat = np.vstack([result.series[n][1] for n in result.series])
    assert len({row.tobytes() for row in ymat}) == len(kept), "两条曲线完全一样"
    info_text = ptab._info.text()
    assert "条曲线" in info_text or "curve" in info_text, \
        f"状态栏应汇报曲线条数：{info_text}"
    legend = result.axes.get_legend()
    labels = [t.get_text() for t in legend.get_texts()] if legend else []
    assert sorted(labels) == sorted(kept), f"图例应与曲线一一对应，实际 {labels}"


def _synthetic_binary_image():
    """合成二元相图：坐标框 + 实线网格 + 一条斜相界。返回 (数组, 框坐标)。"""
    arr = np.full((400, 600, 3), 255, dtype=np.uint8)
    x0, x1, y0, y1 = 80, 560, 40, 360
    arr[y0, x0:x1] = arr[y1, x0:x1] = (0, 0, 0)
    arr[y0:y1, x0] = arr[y0:y1, x1] = (0, 0, 0)
    for y in range(80, y1, 40):
        arr[y, x0:x1] = (0, 0, 0)
    for x in range(140, x1, 60):
        arr[y0:y1, x] = (0, 0, 0)
    for i in range(400):
        arr[300 - int(i * 200 / 400), 100 + i] = (0, 0, 0)
    return arr, (x0, x1, y0, y1)


def test_digitize_tab_present_and_usable_without_database() -> None:
    """数字化不依赖数据库：没载入 TDB 时该页也要能点开。"""
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    tabs = [win._side_tabs.tabText(i) for i in range(win._side_tabs.count())]
    assert i18n.tr("数字化相图") in tabs, tabs
    idx = win._side_index(win._digitize_tab)
    assert win._side_tabs.isTabEnabled(idx), "数字化页应始终可用"
    assert win._stack.count() == 3, "中央应有 引导 / 相图 / 图像 三页"
    # 图像页默认不显示，导入后才切过去
    assert win._stack.currentWidget() is not win._image_host


def test_import_image_switches_to_image_page() -> None:
    """导入图像：中央切到图像页，画布挂上图，右侧自动跳到数字化页。"""
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    arr, _ = _synthetic_binary_image()
    win.load_image(arr)
    assert win._stack.currentWidget() is win._image_host
    assert win._image_canvas.has_image()
    assert win._side_tabs.currentWidget() is win._side_scrolls[win._digitize_tab]
    shown = win._digitize_tab._original
    assert shown is not None and shown.shape[:2] == arr.shape[:2]


def test_digitize_end_to_end_produces_rows() -> None:
    """完整五步：标定 → 去网格 → 画区域 → 出数据，且区域按顺序上下拼接。"""
    from PyQt6.QtWidgets import QInputDialog

    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    tab = win._digitize_tab
    arr, (x0, x1, y0, y1) = _synthetic_binary_image()
    win.load_image(arr)

    # 2. 标定：左下 / 右下 / 左上
    tab._toggle_calib()
    assert tab._mode == "calib"
    for point in ((x0, y1), (x1, y1), (x0, y0)):
        tab._on_canvas_clicked(*point)
    assert tab._calib.ready
    # 换算出的数据坐标要对得上：底边中点 → x=0.5，T=300
    mx, my = tab._calib.to_data((x0 + x1) / 2.0, y1)
    assert abs(mx - 0.5) < 1e-6 and abs(my - 300.0) < 1.0

    # 3. 去网格线
    tab._remove_grid()
    grid_text = tab._grid_info.text()
    assert "已去除" in grid_text or "Removed" in grid_text, grid_text

    def region(points, label):
        tab._start_region()
        for p in points:
            tab._on_canvas_clicked(*p)
        QInputDialog.getText = staticmethod(lambda *a, **k: (label, True))
        tab._finish_region()

    # 4. 两个区域：顶点一律取"斜相界 + 底框"，底框那条靠投影兜底
    #    （网格线已被抹掉，不能把顶点落在网格线上，否则吸附不到）
    region([(150, 272), (250, 222), (350, 172), (450, 122), (450, 357), (150, 357)],
           "BCC")
    region([(150, 357), (350, 357), (350, 172)], "FCC")
    assert len(tab._regions) == 2, [r.label for r in tab._regions]
    assert tab._current_points == [], "完成区域后当前点应清空"

    # 5. 生成数据
    tab._generate()
    assert tab._table.rowCount() > 0, "应生成数据行"
    frame = tab._frame
    assert set(frame["区域"]) == {1, 2}
    ids = list(frame["区域"])
    # 后一个区域的点必须排在前一个下面（不是交错）
    assert ids.index(2) > max(i for i, v in enumerate(ids) if v == 1)
    assert set(frame["相标签"]) == {"BCC", "FCC"}
    cols = [str(c) for c in frame.columns]
    assert "区域" in cols and "相标签" in cols and "T (K)" in cols, cols
    # 成分必须在 0~1 之间
    xcol = [c for c in cols if c.startswith("X(")][0]
    values = frame[xcol].astype(float)
    assert values.min() >= 0.0 and values.max() <= 1.0


def test_digitize_right_click_deletes_nearest_point() -> None:
    """右键点图删掉最近的点（边界点优先）。"""
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    tab = win._digitize_tab
    arr, (x0, x1, y0, y1) = _synthetic_binary_image()
    win.load_image(arr)
    tab._toggle_calib()
    for point in ((x0, y1), (x1, y1), (x0, y0)):
        tab._on_canvas_clicked(*point)
    assert len(tab._calib.points) == 3
    tab._on_canvas_right_clicked(x0 + 2, y1 - 2)
    assert len(tab._calib.points) == 2, "右键应删掉最近的标定点"
    # 补回来，否则标定不完整、进不了区域标定模式
    tab._on_canvas_clicked(x0, y1)
    assert tab._calib.ready

    # 边界点同理
    tab._start_region()
    tab._on_canvas_clicked(150, 272)
    assert len(tab._current_points) == 1
    tab._on_canvas_right_clicked(*tab._current_points[0])
    assert tab._current_points == [], "右键应删掉最近的边界点"


def test_digitize_canvas_paint_uses_int_coordinates() -> None:
    """绘制路径必须把 float 坐标转成 int：QPainter 的绘制 API 一个 float 都不收。

    T66 回归：`drawPixmap(x, y, w, h, pm)` 里混进 `QPointF.x()` 的浮点会直接
    TypeError（sip 层抛错，进程随后还可能 abort）。**离屏环境不会自动触发
    paintEvent**，所以必须显式调一次才测得出来——否则这条路径一直是"没人跑过"。
    """
    from pycalphad_gui.ui.digitize_canvas import DigitizeCanvas

    arr, (x0, x1, y0, y1) = _synthetic_binary_image()
    canvas = DigitizeCanvas()
    canvas.resize(601, 397)   # 奇数尺寸 → fit_view 的 offset/scale 必是小数
    canvas.show()
    canvas.set_image(arr)
    assert canvas.has_image()

    # 三种光标 + 各类叠加层都过一遍，整条绘制路径不许再有 float 泄漏
    canvas.set_calib_points([(float(x0), float(y1)), (float(x1), float(y1)),
                             (float(x0), float(y0))])
    canvas.set_boundary_points([(150.5, 272.5), (200.25, 250.75)])
    canvas.set_regions([{"points": [(120.5, 300.5), (300.5, 200.5), (200.5, 120.5)],
                         "label": "BCC_A2"}])
    for mode in ("none", "cross", "tri"):
        canvas.set_cursor_mode(mode)
        canvas.paintEvent(None)   # 直接调用，异常才能在 Python 层被捕获
    canvas.set_cursor_mode("none")

    # 缩放/平移之后仍然要能画（offset 变成更"脏"的小数）
    canvas._scale = 1.37
    canvas._offset.setX(-13.6)
    canvas._offset.setY(7.9)
    canvas.paintEvent(None)


# ---------------------------------------------------------------------------
# 双语支持（i18n）
# ---------------------------------------------------------------------------
def _cjk_literals() -> list:
    """源码里所有含汉字的字符串常量（跳过 docstring / 词典自身 / QSS）。

    返回 ``[(相对路径, 行号, 文本)]``。
    """
    import ast

    pkg = ROOT / "pycalphad_gui"
    out: list = []
    for path in sorted(pkg.rglob("*.py")):
        rel = path.relative_to(pkg).as_posix()
        if "__pycache__" in path.parts or "build" in path.parts:
            continue
        if rel in {"i18n.py", "i18n_zh_en_core.py", "i18n_zh_en_ui.py",
                   "i18n_zh_en_macro.py"}:
            continue
        if rel == "ui/theme.py":
            continue  # 纯 QSS / 配色：样式串不是文案，按设计不翻译
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)) and body \
                    and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                skip.add(id(body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and id(node) not in skip \
                    and isinstance(node.value, str):
                out.append((rel, node.lineno, node.value))
    return out


def test_i18n_dictionary_is_complete() -> None:
    """源码里**每一个**含汉字的字面量都要能被完整翻成英文。

    这里踩过一个坑：f-string 在 AST 里是 ``JoinedStr``，整串带着变量、
    永远进不了词典，运行时靠"片段替换"兜底。所以要求不是"整串在词典里"，
    而是**每个含汉字的常量片段自己就是词典的键**。只检查整串字面量的
    扫描会给出"0 未覆盖"的假绿（T68）。
    """
    from pycalphad_gui import i18n

    hard, partial = [], []
    for rel, line, text in _cjk_literals():
        if not i18n.has_cjk(text):
            continue
        out = i18n.tr_to(text, "en")
        if out == text:
            hard.append((rel, line, text))
        elif i18n.has_cjk(out):
            partial.append((rel, line, text, out))
    assert not hard, f"这些文案完全没进词典：{hard[:5]}"
    assert not partial, f"这些文案翻完还残留汉字：{partial[:5]}"


def test_i18n_translation_is_reversible_and_idempotent() -> None:
    """两个方向都要能翻，且重复翻译不再变化（否则整树扫两遍就翻花了）。

    ``tr(tr(x)) == tr(x)`` 是"启动扫一遍 + 新建控件再翻一次"能共存的前提。
    """
    from pycalphad_gui import i18n
    from pycalphad_gui.i18n import CORE_ZH_EN, UI_ZH_EN

    for zh, en in {**CORE_ZH_EN, **UI_ZH_EN}.items():
        if en is None or not i18n.has_cjk(zh):
            continue
        assert i18n.tr_to(zh, "en") == en, zh
        assert not i18n.has_cjk(i18n.tr_to(zh, "en")), zh
        # 反向可能"多对一"（同一句英文对应多个中文），只要求幂等 + 无汉字残留
        back = i18n.tr_to(en, "zh")
        # 长度 < 4 的英文值（"·" → "." 这类标点）刻意不建反向，防止切回
        # 中文时咬坏英文句子里的正常标点；这类只要求"不崩、幂等"
        if len(en) >= 4:
            assert i18n.has_cjk(back), (en, back)
        # 反向可能"多对一"（同一句英文对应不止一个中文），只要求幂等
        assert i18n.tr_to(i18n.tr_to(en, "zh"), "zh") == back, en
        assert i18n.tr_to(en, "en") == en, en

    # 纯数据（数值 / 相名 / 元素符号）必须原样返回，一个字符都不能动
    for raw in ("BCC_A2", "ALZN", "12.5", "α-Al", "μ"):
        assert i18n.tr_to(raw, "en") == raw
        assert i18n.tr_to(raw, "zh") == raw


def test_i18n_single_char_keys_stay_out_of_fragments() -> None:
    """单字键不许进片段表——否则会去咬任何一句没收录的中文。

    ``"相"``、``"是"`` 这类单字一旦参与片段替换，"这是…" 就会被翻花；
    标点是例外（它本来就是拼句子的粘合剂）。
    """
    from pycalphad_gui import i18n

    for key in i18n._ZH_KEYS:
        assert len(key) >= 2 or key in i18n._PUNCT_KEYS, key
    for key in i18n._EN_KEYS:
        assert len(key) >= 4, key


def test_language_defaults_to_english_and_button_is_on_menu_row() -> None:
    """默认语言是英文；切换入口挂在菜单栏右上角（右侧面板可被隐藏，靠不住）。"""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QToolButton

    from pycalphad_gui import i18n
    from pycalphad_gui.ui.main_window import MainWindow

    assert i18n.DEFAULT_LANG == "en"
    assert i18n.LANGS == ("en", "zh")
    win = MainWindow()
    btn = win.menuBar().cornerWidget(Qt.Corner.TopRightCorner)
    assert isinstance(btn, QToolButton), btn
    assert [a.text() for a in btn.menu().actions()] == ["English", "中文"]
    # 语言自称不进词典：切语言时按钮上的字不能跟着变
    for name in i18n.LANG_NAMES.values():
        assert not i18n.known(name)


def test_language_switch_translates_ui_and_keeps_internal_keys() -> None:
    """切一次语言：可见文案跟着走，但**内部键**必须纹丝不动。

    "把显示文本当内部 key"是这个项目最容易踩的坑（``diagram_type()`` 一度
    返回的是下拉框的显示文字，切到英文后 ConditionPlan 就认不出来了）。
    """
    from pycalphad_gui import i18n
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    saved = i18n.load_saved_lang()
    try:
        win.set_language("en")
        assert i18n.lang() == "en"
        titles = [win._side_tabs.tabText(i) for i in range(win._side_tabs.count())]
        assert not any(i18n.has_cjk(t) for t in titles), titles
        assert "Diagram Calculation" in titles

        # 内部键与显示语言无关
        assert win._diagram_panel._panel.diagram_type() == "binary_ztpf"
        combos = win._diagram_panel._panel._diagram
        assert combos.currentData() == "binary_ztpf", combos.currentData()

        win.set_language("zh")
        titles = [win._side_tabs.tabText(i) for i in range(win._side_tabs.count())]
        assert "相图计算" in titles, titles
        assert win._diagram_panel._panel.diagram_type() == "binary_ztpf"
    finally:
        win.set_language(saved)
        i18n.save_lang(saved)


def test_language_switch_leaves_no_chinese_in_english_mode() -> None:
    """英文模式下，界面上不该还剩汉字（语言自称"中文"除外）。

    这是词典覆盖率的**控件级**复核：AST 审计看的是源码字面量，这里看的是
    真正挂到窗口上的那批文本——"扫到但没生效"（比如漏了 setTitle）只有
    走到控件树才暴露。
    """
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QComboBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QTextEdit,
        QWidget,
    )

    from pycalphad_gui import i18n
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1440, 900)
    saved = i18n.load_saved_lang()
    try:
        win.set_language("en")
        offenders: list = []

        def _collect(text: str, where: str) -> None:
            if text and i18n.has_cjk(text) and text != "中文":
                offenders.append(f"{where}: {text!r}")

        for w in [win] + win.findChildren(QWidget) + win.findChildren(QAction):
            if isinstance(w, QLabel):
                _collect(w.text(), type(w).__name__)
            elif isinstance(w, QAbstractButton):
                _collect(w.text(), type(w).__name__)
            elif isinstance(w, QGroupBox):
                _collect(w.title(), "QGroupBox.title")
            elif isinstance(w, QLineEdit):
                _collect(w.placeholderText(), "QLineEdit.placeholder")
            elif isinstance(w, (QTextEdit, QPlainTextEdit)):
                # 多行编辑框的占位提示也要翻（宏编辑区 / 命令输入框）
                _collect(w.placeholderText(), f"{type(w).__name__}.placeholder")
            elif isinstance(w, QComboBox):
                for i in range(w.count()):
                    _collect(w.itemText(i), "QComboBox.item")
            elif isinstance(w, QAction):
                _collect(w.text(), "QAction")
        assert not offenders, offenders[:8]
    finally:
        win.set_language(saved)
        i18n.save_lang(saved)


def test_macro_command_transcript_follows_language_switch() -> None:
    """命令页回显与示例下拉都要能跟着语言切回去。

    回显是只读多行文本，整树遍历刻意跳过（里面大多是运行数据），必须靠
    ``MacroTab.retranslate()`` 按原始中文重放；示例下拉里是**文件路径**，
    不能让片段翻译把 "phase" 改成"相"——中文单字不进片段表，切回英文时
    这条路径就再也拼不回去了。
    """
    from pycalphad_gui import i18n
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    saved = i18n.load_saved_lang()
    try:
        win.set_language("zh")
        tab = win._macro_tab
        tab._command_input.setText("?")
        tab._on_command_submitted()
        assert "宏命令一览" in tab._command_view.toPlainText()

        win.set_language("en")
        text = tab._command_view.toPlainText()
        assert "Macro commands" in text, text
        assert not i18n.has_cjk(text), text

        labels = [tab._examples_box.itemText(i)
                  for i in range(tab._examples_box.count())]
        assert any("04_phase_fractions_vs_t.pcm" in label for label in labels), labels
        assert not any(i18n.has_cjk(label) for label in labels), labels

        win.set_language("zh")
        assert tab._btn_command_run.text() == "执行"
        assert tab._path_label.text() == "未保存"
    finally:
        win.set_language(saved)
        i18n.save_lang(saved)


def test_startup_opens_on_diagram_tab_and_maximizes() -> None:
    """打开界面停在「相图计算」，并且是最大化开的。"""
    from pycalphad_gui import app as app_module
    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    assert win._side_tabs.currentWidget() is win._side_scrolls[win._diagram_panel]
    assert win._side_tabs.tabText(0) in ("相图计算", "Diagram Calculation")
    # 最大化放在 app.main() 里（离屏测试要能保持普通尺寸），所以这里查开关
    assert app_module.START_MAXIMIZED is True
    assert "showMaximized" in inspect.getsource(app_module.main)



def test_side_panels_do_not_inflate_window_and_shrink_proportionally() -> None:
    """右栏页面不能撑大窗口；手动缩小时三栏按比例收窄。

    回归两个用户实测问题：
    1. 宏页顶部一行"示例 + 三个按钮"把页面最小宽顶到 838px，右侧「计算」
       面板随之被撑宽、中央画布被压扁；
    2. ESPEI 整表单最小高 826px，把整窗最小高抬到 988px，笔记本上最大化
       也塞不进屏幕，窗口底部的日志 / 进度条被挤到屏幕外。
    """
    from PyQt6.QtWidgets import QScrollArea

    from pycalphad_gui.ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1600, 900)
    win.show()
    win._side_show(win._macro_tab)
    QApplication.processEvents()

    assert win._macro_tab.minimumSizeHint().width() <= 300
    assert win.minimumSizeHint().height() <= 700
    for page, scroll in win._side_scrolls.items():
        assert isinstance(scroll, QScrollArea)
        assert scroll.widget() is page
        assert win._side_tabs.indexOf(scroll) >= 0

    right = win._right_dock.width()
    size = (win.width(), win.height())
    win._macro_tab._append_log("x" * 500)
    QApplication.processEvents()
    assert (win.width(), win.height()) == size, "追加日志不应改变窗口尺寸"
    assert win._right_dock.width() == right, "宏页内容不应撑大右侧面板"

    win.resize(1200, 780)
    QApplication.processEvents()
    assert win._right_dock.width() <= right, "缩小窗口时右栏不应反向变宽"


def test_display_spin_separates_display_and_value() -> None:
    """数字框"显示位数"与"存储精度"分离（用户反馈：默认 4 位太啰嗦）。

    - 温度显示 1 位、成分显示 3 位，但存储精度（decimals）不变；
    - 输入超过存储位数的小数要被**接受**（Qt 默认会静默丢弃，
      输 0.333333 回车直接弹回 0.0——必须放宽 validate）；
    - 乱码输入兜底为保持原值，不崩不跳变。
    """
    from pycalphad_gui.ui.spinboxes import DisplaySpin

    s = DisplaySpin(1)
    s.setRange(0.0, 10000.0)
    s.setDecimals(4)
    s.setValue(300.25)
    assert s.value() == 300.25, s.value()
    assert s.text() == "300.3", s.text()  # 半进位，不是银行家舍入

    s.set_display_decimals(3)
    assert s.text() == "300.250", s.text()

    # 超位数输入：接受，按显示位数渲染、精度不丢
    s.lineEdit().setText("0.333333")
    s.interpretText()
    assert s.value() == 0.333333, s.value()
    assert s.text() == "0.333", s.text()

    # 乱码兜底：保持原值
    s.lineEdit().setText("garbage")
    s.interpretText()
    assert s.value() == 0.333333, s.value()

    # 扫描行联动：T 行显示 1 位，成分行显示 3 位
    from pycalphad_gui.ui.condition_panel import SweepRow

    row = SweepRow(["T", "AL", "P"])
    row.set_target("T")
    assert row.start.text() == "300.0", row.start.text()
    row.set_target("AL")
    assert row.start.text() == "0.000", row.start.text()



def test_step_plot_y_option_reaches_engine() -> None:
    """Step 图改 y 轴后必须真的生效（回归：diagram_panel 提交时直接取了
    内层条件面板的 plot_options，把 step_y 整个丢掉，出的图永远是相分数）。"""
    import matplotlib

    matplotlib.use("Agg")
    from pycalphad_gui.ui.diagram_panel import DiagramPanel

    from pycalphad_gui.core.database_manager import load_database

    db = load_database(DB_DIR / "CrFeNb_Jacob2016.tdb")
    panel = DiagramPanel()
    panel.configure(db, ["CR", "FE", "NB"], sorted(db.phase_names))

    # 类型切到 Step 图（下拉用 itemData 存内部键）
    inner = panel._panel
    step_idx = inner._diagram.findData("step")
    assert step_idx >= 0
    inner._diagram.setCurrentIndex(step_idx)

    # configure() 会把第二行占位自动填成首个组分；Step 只允许一个扫描维度，
    # 按用户操作删掉这一行，只留温度轴（界面默认不擅自改条件，只在校验时报错）
    inner._remove_row(inner._rows[1])
    inner._rows[0].set_target("T")
    inner.add_fixed_comp_row("FE", 0.4)
    inner.add_fixed_comp_row("NB", 0.2)

    panel._step_y_mode.setCurrentIndex(1)  # 相中元素含量
    panel._step_y_elem.setCurrentText("CR")
    opts = panel.plot_options()
    assert opts.get("step_y") == ("x", "CR"), opts

    # 端到端：真算一次，y 轴必须是 X(AL) 而不是相分数
    results = []
    panel.result_ready.connect(lambda r: results.append(r))
    panel.on_draw()
    deadline = time.time() + 180.0
    while time.time() < deadline and panel._btn_draw.isEnabled() is False:
        QApplication.processEvents()
        time.sleep(0.05)
    assert panel._btn_draw.isEnabled(), "Step 图应在超时前完成"
    assert results, "应触发 result_ready"
    assert results[0].axes.lines, "y 轴图上应有曲线"


def test_macro_figure_handoff_waits_for_worker() -> None:
    """宏的结果图必须等 worker 结束后才交给主窗口。

    回归：worker 发出 figure 信号后还会继续执行 ``EXPORT FIGURE``
    （对同一张 Figure 调 savefig）。主线程若立刻把它包成
    ``FigureCanvasQTAgg``，worker 线程再 savefig 就会跨线程碰 QWidget，
    PyQt 报 "super-class __init__() of type FigureCanvasQTAgg was never
    called"：导出失败，画布还会被回写成 Agg 而一片空白。
    """
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    from pycalphad_gui.core.macro_engine import MacroResult
    from pycalphad_gui.ui.macro_tab import MacroTab

    tab = MacroTab()
    seen: list = []
    tab.figure_ready.connect(lambda fig, axes, caption: seen.append("figure"))
    tab.busy_changed.connect(lambda running: seen.append(("busy", running)))

    figure = Figure()
    ax = figure.add_subplot(111)
    ax.plot([0.0, 1.0], [0.0, 1.0])
    tab._on_figure(figure, [ax], "caption")
    assert seen == [], "worker 未结束前不应把 Figure 交给主窗口"

    tab._on_success(MacroResult(n_commands=1, n_results=1))
    assert seen == ["figure", ("busy", False)], seen


def test_command_panel_help_and_completion() -> None:
    """命令页：? 帮助、命令 ? 详情、Tab 上下文补全。"""
    from pycalphad_gui.core.database_manager import load_database
    from pycalphad_gui.ui.macro_tab import MacroTab

    tab = MacroTab()
    assert tab._result_tabs.count() == 3, "命令页应排在输出日志 / 结果表之后"
    assert tab._result_tabs.tabText(2) == "命令"
    assert tab._result_tabs.widget(2) is tab._command_panel

    tab._command_input.setText("?")
    tab._on_command_submitted()
    overview = tab._command_view.toPlainText()
    for word in ("OPEN", "ELEMENTS", "DIAGRAM", "EXPORT"):
        assert word in overview, f"总览里没有 {word}"

    tab._command_input.setText("OPEN ?")
    tab._on_command_submitted()
    assert "OPEN <TDB/DAT>" in tab._command_view.toPlainText()

    tab._command_input.setText("NOPE ?")
    tab._on_command_submitted()
    assert "NOPE" in tab._command_view.toPlainText()

    tab._command_input.setText("EL")
    tab._command_input.setCursorPosition(2)
    tab._on_tab_completion()
    assert tab._command_input.text() == "ELEMENTS"

    tab.configure(load_database(BIN_DB), ["AL", "ZN"], ["LIQUID", "FCC_A1"])
    tab._command_input.setText("ELEMENTS ")
    tab._command_input.setCursorPosition(len("ELEMENTS "))
    tab._on_tab_completion()
    assert tab._command_input.text() == "ELEMENTS AL"

    tab._command_input.setText("DIAGRAM B")
    tab._command_input.setCursorPosition(len("DIAGRAM B"))
    tab._on_tab_completion()
    assert tab._command_input.text() == "DIAGRAM BINARY"

    # 同一个位置连续按 Tab：在候选之间轮换
    tab._command_input.setText("P")
    tab._command_input.setCursorPosition(1)
    tab._on_tab_completion()
    first = tab._command_input.text()
    tab._on_tab_completion()
    assert tab._command_input.text() != first, "第二次 Tab 应换下一个候选"


def test_command_panel_runs_one_step() -> None:
    """命令页能真的跑一条命令，并把文字输出留在本页。"""
    from pycalphad_gui.ui.macro_tab import MacroTab

    app = QApplication.instance()
    assert app is not None
    tab = MacroTab()
    busy: list = []
    tab.busy_changed.connect(busy.append)

    tab._command_input.setText("SHOW")
    tab._on_command_submitted()

    deadline = time.time() + 20
    while tab._running and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()

    assert not tab._running, "命令应在超时前结束"
    assert busy and busy[0] is True and busy[-1] is False, busy
    text = tab._command_view.toPlainText()
    assert "> SHOW" in text, text
    assert "Status" in text or "状态" in text, text
    assert tab._session is not None and tab._session.started
    assert tab._command_input.isEnabled(), "命令结束后输入框应恢复可用"


def main() -> int:
    if QApplication is None:  # pragma: no cover
        print("未安装 PyQt6，跳过 GUI 冒烟测试")
        return 0

    import matplotlib

    # 与 app.main() 保持一致：后台线程用 Agg 出图，Qt 画布只在主线程挂上
    matplotlib.use("Agg")

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")

    check("主窗口构造", test_window_constructs)
    check("未载入时的引导状态", test_empty_state_before_load)
    check("载入后引导消失且功能页可用", test_empty_state_cleared_after_load)
    check("载入数据库刷新界面", test_load_database_refreshes_ui)
    check("排除相", test_exclude_phase)
    check("默认扫描条件可用", test_default_sweep_is_usable)
    check("Qt 画布只在主线程挂载", test_canvas_attached_on_main_thread)
    check("标签与 tie line 交互", test_label_and_tieline_interaction)
    check("左键单击放置标注（就地编辑）", test_click_places_label_with_inline_editor)
    check("Shift+拖动生成 tie line", test_shift_drag_creates_tieline)
    check("右键单击删除标注/连线", test_right_click_deletes_under_cursor)
    check("拖动标注后手势状态不泄漏", test_label_drag_does_not_leak_state)
    check("温度扫描行可编辑", test_state_sweep_row_is_editable)
    check("legend 可拖动", test_legend_is_draggable_after_set_figure)
    check("复位视图恢复初始范围", test_reset_view_restores_initial_limits)
    check("VA 与 /- 位于第 1 行空白格", test_pseudo_cells_sit_in_top_row)
    check("周期表无需滚动即可看全", test_periodic_table_fits_without_scroll)
    check("周期表单击/Shift点击不报错", test_cycle_clicks_never_touch_missing_api)
    check("界面里没有模式下拉框", test_no_mode_selector_in_view)
    check("工具栏视图动作齐全", test_view_toolbar_actions_exist)
    check("属性页扫温度时要求固定组分", test_property_tab_fixed_inputs_follow_scan_axis)
    check("属性页真算一遍且曲线可见", test_property_tab_end_to_end_visible_curve)
    check("属性页默认逐相且每相一条", test_property_tab_per_phase_default)
    check("后台线程绘制二元相图", test_plot_small_binary)
    check("GUI 导出 PNG", test_export_from_gui)
    check("高通量共存相数列有数字", test_ht_tab_nphases_column_is_filled)
    check("勾选元素收窄各面板候选", test_selected_elements_limit_panel_candidates)
    check("点添加扫描维度不崩", test_add_sweep_row_button_does_not_crash)
    check("勾选库外元素不打断联动", test_out_of_database_element_does_not_break_linkage)
    check("预选点亮两字母元素按钮", test_set_selection_checks_buttons_case_insensitive)
    check("多元素库载入不预选", test_multi_element_database_starts_without_selection)
    check("数字化页无需数据库即可用", test_digitize_tab_present_and_usable_without_database)
    check("导入图像切到图像页", test_import_image_switches_to_image_page)
    check("数字化五步出数据且区域拼在下", test_digitize_end_to_end_produces_rows)
    check("右键点图删最近的点", test_digitize_right_click_deletes_nearest_point)
    check("图像画布绘制不传 float 给 QPainter",
          test_digitize_canvas_paint_uses_int_coordinates)

    check("宏结果图等 worker 结束再交付", test_macro_figure_handoff_waits_for_worker)
    check("命令页帮助与 Tab 补全", test_command_panel_help_and_completion)
    check("命令页逐步执行一条命令", test_command_panel_runs_one_step)
    check("命令回显与示例路径跟随语言切换",
          test_macro_command_transcript_follows_language_switch)

    check("词典覆盖源码里每一处汉字", test_i18n_dictionary_is_complete)
    check("翻译可逆且幂等、纯数据不动", test_i18n_translation_is_reversible_and_idempotent)
    check("单字键不进片段表", test_i18n_single_char_keys_stay_out_of_fragments)
    check("默认英文且切换按钮在菜单栏右上角",
          test_language_defaults_to_english_and_button_is_on_menu_row)
    check("切语言不动内部键", test_language_switch_translates_ui_and_keeps_internal_keys)
    check("英文模式下界面无汉字残留",
          test_language_switch_leaves_no_chinese_in_english_mode)
    check("启动停在相图计算页且最大化",
          test_startup_opens_on_diagram_tab_and_maximizes)

    check("数字框显示位数与存储精度分离",
          test_display_spin_separates_display_and_value)

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n通过 {passed}/{total}")
    for name, ok, msg in results:
        if not ok:
            print(f"  · {name}: {msg}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

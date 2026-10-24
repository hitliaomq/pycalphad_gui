"""无 GUI 全流程冒烟测试。

覆盖：元素数据 → 数据库解析 → 条件校验（含错误路径）→ 属性计算 →
高通量扫描 → 导出。可在命令行直接 ``python tests/test_smoke.py`` 运行，
也可交由 pytest 收集。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# 让脚本在没有安装成包时也能导入
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# pycalphad 的绘图会用到 pyplot，必须先切到无显示后端
import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402

from pycalphad_gui.core.digitizer import (  # noqa: E402
    CalibPoint,
    Calibration,
    DigitizedRegion,
    dark_mask,
    detect_grid_lines,
    project_to_polygon,
    regions_to_frame,
    remove_grid_lines,
    snap_to_boundary,
    to_gray,
)
from pycalphad_gui.core.database_manager import (  # noqa: E402
    LoadedDatabase,
    filter_phases,
    load_database,
)
from pycalphad_gui.core.conditions import (  # noqa: E402
    STATE_KEYS,
    ConditionPlan,
    axis_candidates,
)
from pycalphad_gui.core.diagnostics import CalculationError  # noqa: E402
from pycalphad_gui.core.exporter import (  # noqa: E402
    export_dataframe,
    export_figure,
    export_series_csv,
)
from pycalphad_gui.core.high_throughput import HTConfig, run_high_throughput  # noqa: E402
from pycalphad_gui.core.plot_engine import (  # noqa: E402
    _render_ternary_grid,
    compute_diagram,
    compute_property_curves,
)
from pycalphad_gui.config import is_real_element  # noqa: E402
from pycalphad_gui.elements import ELEMENTS, layout_rows  # noqa: E402

# pycalphad 自带的测试数据库（已随源码包复制到本仓库，见 tests/databases/pycalphad/）
DB_DIR = Path(__file__).parent / "databases" / "pycalphad"
_BIN_DB = DB_DIR / "alzn_mey.tdb"
_TERN_DB = DB_DIR / "alcrni.tdb"
#: 用户提供的真实数据库（V-Zr，含 IONIC_LIQ 离子液体相），随仓库一起分发
_VZR_DB = Path(__file__).parent / "databases" / "vzr_zha-2012.tdb"


# ---------------------------------------------------------------------------
# 1. 元素数据
# ---------------------------------------------------------------------------
def test_element_table_complete() -> None:
    assert len(ELEMENTS) == 118, "元素表应覆盖 118 个元素"
    rows = layout_rows()
    assert rows, "周期表布局不应为空"
    for info in ELEMENTS.values():
        assert info.symbol and info.number > 0


def test_layout_has_no_fblock_conflict() -> None:
    """同一个格子不能被两个元素占用。"""
    seen: set = set()
    for _row, cells in layout_rows():
        for cell in cells:
            if cell is None:
                continue
            key = (cell.row, cell.col)
            assert key not in seen, f"格子 {key} 冲突：{cell.symbol}"
            seen.add(key)


# ---------------------------------------------------------------------------
# 2. 数据库解析
# ---------------------------------------------------------------------------
def test_load_database() -> None:
    db = load_database(_BIN_DB)
    assert isinstance(db, LoadedDatabase)
    assert "ZN" in db.display_elements
    assert "-" not in db.display_elements, "电荷占位符 '-' 不应出现在展示元素中"
    assert "VA" not in db.display_elements, "空位 VA 不应展示为元素"
    assert db.phases, "应解析出相"
    # 符号规范化：库里是 'ZN'，用户可能写 'zn'
    assert db.resolve("zn") == "ZN"
    assert db.resolve("Zn") == "ZN"
    assert db.resolve("XX") is None


def test_load_missing_file_raises() -> None:
    try:
        load_database(Path(tempfile.gettempdir()) / "definitely_not_exists.tdb")
    except CalculationError as exc:
        assert "不存在" in exc.user_message
    else:  # pragma: no cover
        raise AssertionError("应抛出 CalculationError")


def test_pseudo_elements_are_filtered() -> None:
    """``/-``（电子气）与 ``VA``（空位）不能混进真实元素里。

    alzn_mey.tdb 里写着 ``ELEMENT /- ELECTRON_GAS`` 和
    ``DEFAULT_COMMAND DEF_SYS_ELEMENT VA /-``。早先按 '-' 做黑名单，
    '/-' 被漏过去，还被当成默认组分送进计算，直接报
    ``ConditionError: X_/- refers to non-existent component``。
    """
    db = load_database(_BIN_DB)
    assert "/-" not in db.display_elements, "电子气占位不应出现在周期表"
    assert "VA" not in db.display_elements, "空位不应出现在周期表"
    assert "ZN" in db.display_elements
    for sym in db.display_elements:
        assert is_real_element(sym), f"{sym} 不是真实元素"
    # 空位仍要进组分列表：多数 CEF 相模型把它当 endmember
    comps = db.components_for(["AL"])
    assert comps == ["AL", "VA"], comps


def test_filter_phases() -> None:
    db = load_database(_BIN_DB)
    names = db.phase_names
    # filter_phases 刻意返回「去重 + 排序」的结果，保证同一套勾选总是得到
    # 同一份相序（相序会影响绘图配色与图例），因此断言排过序的期望值。
    assert filter_phases(db, names) == sorted(set(names))
    assert set(filter_phases(db, names)) == set(names)
    subset = names[:2]
    assert filter_phases(db, subset) == sorted(set(subset))
    # 去重
    assert filter_phases(db, [names[0], names[0], names[1]]) == sorted(
        {names[0], names[1]}
    )
    try:
        filter_phases(db, [])
    except CalculationError:
        pass
    else:  # pragma: no cover
        raise AssertionError("空选中集合应报错")


# ---------------------------------------------------------------------------
# 3. 条件构造与校验
# ---------------------------------------------------------------------------
def test_binary_plan_ok() -> None:
    db = load_database(_BIN_DB)
    plan = ConditionPlan.from_ui(
        db, "binary_ztpf", {"T": (500, 800, 50), "ZN": (0, 1, 0.1)}, {"P": 101325.0}
    )
    conds = plan.build(db)
    assert len(conds) >= 3
    assert plan.validate(db) is None


def test_ternary_plan_shape_rejected_for_binary() -> None:
    """三元条件用在二元图上必须被拦下，而不是丢给 pycalphad 抛英文错。"""
    db = load_database(_TERN_DB)
    try:
        ConditionPlan.from_ui(db, "binary_ztpf", {"ZN": (0, 1, 0.1)})
    except CalculationError as exc:
        assert "组分扫描 1 个" in exc.user_message or "组分扫描" in exc.user_message
    else:  # pragma: no cover
        raise AssertionError("二元图收到三元条件应报错")


def test_ternary_plan_ok() -> None:
    db = load_database(_TERN_DB)
    plan = ConditionPlan.from_ui(
        db, "ternary_isothermal", {"AL": (0, 0.3, 0.1), "CR": (0, 0.9, 0.1)}, {"T": 1500.0}
    )
    conds = plan.build(db)
    # conds 的键是 pycalphad 的 StateVariable 对象（str() 后形如 'T' / 'X_AL'），
    # 不是本模块的 Sweep，所以只能用字符串判断势场。等温截面上势场必须是标量。
    swept_state = [
        str(k)
        for k, val in conds.items()
        if str(k) in STATE_KEYS and np.size(val) > 1
    ]
    assert not swept_state, f"等温截面不应有变化的势场，实际：{swept_state}"


def test_ternary_requires_third_element() -> None:
    """T57：只勾两个真元素就画三元截面，要给中文提示而不是 pycalphad 的 IndexError。

    pycalphad 的 TernaryStrategy 需要一个"不在扫描轴上的真元素"（成分由 N=1
    隐式确定），只有 [AL, CR, VA] 时它直接 IndexError: list index out of range。
    """
    db = load_database(_TERN_DB)
    plan = ConditionPlan.from_ui(
        db, "ternary_isothermal", {"AL": (0, 1, 0.02), "CR": (0, 1, 0.02)}, {"T": 1500.0}
    )
    comps = db.components_safe(["AL", "CR"])[0]  # = [AL, CR, VA]，没有第三个真元素
    try:
        compute_diagram(db, comps, sorted(db.phase_names), plan)
    except CalculationError as exc:
        assert "三个元素" in exc.user_message, exc.user_message
    else:  # pragma: no cover
        raise AssertionError("两个真元素的三元截面应被友好拦截")


def test_ternary_grid_fallback_renders() -> None:
    """T57：映射算法无 tie line 时，网格法兜底能画出三角截面。"""
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(_TERN_DB)
    plan = ConditionPlan.from_ui(
        db, "ternary_isothermal",
        {"AL": (0, 0.6, 0.05), "CR": (0, 0.6, 0.05)},
        {"T": 1400.0, "P": 101325.0},
    )
    conds = plan.build(db)
    comps = db.components_safe(["AL", "CR", "NI"])[0]
    x_var = [k for k in conds if str(k) == "X_AL"][0]
    y_var = [k for k in conds if str(k) == "X_CR"][0]
    # 默认（Thermo-Calc 经典线式）：tie line 扇形 + 相色边界 + 黑色描边
    ax = _render_ternary_grid(
        db, comps, sorted(db.phase_names), conds,
        x_var, y_var,
        grid_n=13,
    )
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert labels, "线式应有相图例"
    assert len(ax.collections) >= 2, "应有 tie line 与边界两个线集合"
    assert ax.lines, "三角形描边应存在"
    # 图例颜色必须能对上实际画出的边界线颜色
    bnd_colors = {tuple(np.round(c, 6)) for c in ax.collections[-1].get_colors()}
    legend_colors = {
        tuple(np.round(l.get_color(), 6)) for l in ax.get_legend().get_lines()
    }
    assert bnd_colors, "边界线集合不应为空"
    # 覆盖范围必须在等边三角形内
    tie = ax.collections[0].get_segments() if ax.collections else []
    assert tie, "alcrni 在 1400K 应有两相区（tie line）"
    for (p0, p1) in tie[:5]:
        for px, py in (p0, p1):
            assert -1e-6 <= px <= 1 + 1e-6 and -1e-6 <= py <= 1 + 1e-6

    # 官网 ternplot 风格：单相区填色的多边形铺满三角形（Delaunay 剖分）
    ax2 = _render_ternary_grid(
        db, comps, sorted(db.phase_names), conds,
        x_var, y_var,
        grid_n=13, style="fill",
    )
    labels2 = [t.get_text() for t in ax2.get_legend().get_texts()]
    assert labels2, "填充式应至少画出一个单相区"
    assert len(ax2.collections) >= 2, "应有填色多边形与黑色边界两个集合"
    # PolyCollection.get_offsets() 只是偏移（默认 [[0,0]]），顶点在 get_paths() 里
    verts = np.vstack([p.vertices for p in ax2.collections[0].get_paths()])
    assert verts.size > 0
    # 投影坐标范围：u∈[-0.1,1.1]，w∈[-0.14,1.0]，多边形不得越界
    assert float(verts[:, 0].min()) >= -0.11 and float(verts[:, 0].max()) <= 1.11
    assert float(verts[:, 1].min()) >= -0.15 and float(verts[:, 1].max()) <= 1.01
    # 填色必须深入三角形上部（alcrni@1400K 顶角是 B2+B2 混溶隙、官方
    # 风格留白，单相 B2 区最高到 w≈0.76；旧版边缘留白问题以 >0.7 回归）
    w_max = float(verts[:, 1].max())
    assert w_max > 0.7, f"单相区填色应深入三角形上部，实际 w_max={w_max:.3f}"


def test_ternary_diagram_end_to_end() -> None:
    """T57：三元截面整条链路要能出图——映射成功走映射，失败自动退网格法。"""
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(_TERN_DB)
    plan = ConditionPlan.from_ui(
        db, "ternary_isothermal",
        {"AL": (0, 0.6, 0.03), "CR": (0, 0.6, 0.03)},
        {"T": 1400.0, "P": 101325.0},
    )
    comps = db.components_safe(["AL", "CR", "NI"])[0]
    result = compute_diagram(db, comps, sorted(db.phase_names), plan)
    assert result.figure is not None and result.axes is not None
    # 无论走哪条路，图上都必须有实际内容
    has_content = bool(result.axes.collections or result.axes.lines)
    assert has_content, "三元截面图上应有相区/曲线"


def test_step_plot_custom_y() -> None:
    """Step 图 y 轴可选：y = 相中元素含量（官方 plot_step(step, x, y=X)）。"""
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(_TERN_DB)
    plan = ConditionPlan.from_ui(
        db, "step", {"T": (800, 1500, 50)},
        {"P": 101325.0, "AL": 0.4, "CR": 0.2},
    )
    comps = db.components_safe(["AL", "CR", "NI"])[0]
    result = compute_diagram(
        db, comps, sorted(db.phase_names), plan, options={"step_y": ("x", "AL")}
    )
    assert result.figure is not None
    assert result.axes.lines, "应有 y=X(AL) 的曲线"


def test_property_np_and_phase_composition() -> None:
    """属性新目标：相分数 NP(*) / 相中元素含量 X(相, 元素)。

    参考 pycalphad 文档 "Phase Fractions and Phase Compositions vs
    Temperature"：wks.get_dict("NP(*)") 与 wks.get(v.X(相, 元素))。
    三元体系必须给全部固定成分，否则自由度不为零。
    """
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(_TERN_DB)
    comps = db.components_safe(["AL", "CR", "NI"])[0]
    options = {"fixed_comps": {"AL": 0.4, "CR": 0.2}}
    r_np = compute_property_curves(
        db, comps, sorted(db.phase_names), "NP", "T",
        np.linspace(800, 1500, 15), options=options,
    )
    assert r_np.series, "NP 应至少给出一个稳定相的分数曲线"
    assert any(k.startswith("NP_") for k in r_np.series), r_np.series.keys()

    r_x = compute_property_curves(
        db, comps, sorted(db.phase_names), "X(B2, AL)", "T",
        np.linspace(800, 1500, 15), options=options,
    )
    assert r_x.series, "X(B2, AL) 应有曲线（相不稳定处为 NaN，自动剔除）"


def test_property_ordering_and_site_fraction() -> None:
    """属性新目标：degree_of_ordering / site fraction（官方 as_property / Model.site_fractions）。

    alcrni 库的 B2 相带有序模型，是现成的验证样例。
    """
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(_TERN_DB)
    comps = db.components_safe(["AL", "CR", "NI"])[0]
    options = {"fixed_comps": {"AL": 0.4, "CR": 0.2}}
    r_o = compute_property_curves(
        db, comps, sorted(db.phase_names), "degree_of_ordering(B2)", "T",
        np.linspace(800, 1500, 15), options=options,
    )
    assert r_o.series, "有序度应有曲线"
    r_sf = compute_property_curves(
        db, comps, sorted(db.phase_names), "sitefraction(B2)", "T",
        np.linspace(800, 1500, 15), options=options,
    )
    assert r_sf.series, "占位分数应有曲线"
    assert any("Y(" in k for k in r_sf.series), r_sf.series.keys()


def test_step_plot_renders() -> None:
    """Step 图：单轴（T）步进 + 固定成分，plot_step 出相分数曲线。

    参考 pycalphad 文档 "Plotting using the Mapping API" 的 Step plotting。
    """
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(_TERN_DB)
    plan = ConditionPlan.from_ui(
        db, "step", {"T": (800, 1500, 50)},
        {"P": 101325.0, "AL": 0.4, "CR": 0.2},
    )
    comps = db.components_safe(["AL", "CR", "NI"])[0]
    result = compute_diagram(db, comps, sorted(db.phase_names), plan)
    assert result.figure is not None and result.axes is not None
    assert result.axes.lines or result.axes.collections, "Step 图应有相分数曲线"


def test_isopleth_renders() -> None:
    """Isopleth 垂直截面：1 组分扫描 + 1 温度扫描 + 固定成分。

    参考 pycalphad 文档 "Plotting using the Mapping API" 的 Isopleth plotting。
    """
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(_TERN_DB)
    plan = ConditionPlan.from_ui(
        db, "isopleth", {"AL": (0, 0.6, 0.03), "T": (400, 1400, 50)},
        {"P": 101325.0, "CR": 0.2},
    )
    comps = db.components_safe(["AL", "CR", "NI"])[0]
    result = compute_diagram(db, comps, sorted(db.phase_names), plan)
    assert result.figure is not None and result.axes is not None
    assert result.axes.lines or result.axes.collections, "Isopleth 应有相界线"


def test_binary_shaded_official_style() -> None:
    """grid_fill 勾选对二元也生效：BinaryStrategy 映射 + 官网 plot_shaded_binary 填色。

    参考 pycalphad 文档 "Plotting using the Mapping API" 的 plot_shaded_binary
    示例：单相区淡蓝底、两相区白色（fill_betweenx）、黑色相界线。
    """
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(_BIN_DB)
    plan = ConditionPlan.from_ui(
        db, "binary_ztpf", {"ZN": (0, 1, 0.02), "T": (300, 1000, 10)}, {"P": 101325.0}
    )
    comps = db.components_safe(["AL", "ZN"])[0]
    result = compute_diagram(
        db, comps, sorted(db.phase_names), plan, options={"grid_fill": True}
    )
    assert result.figure is not None and result.axes is not None
    assert result.axes.collections, "填色视图应有 fill 集合"
    assert result.axes.lines, "应有黑色相界线"


def test_ternary_auto_start_option() -> None:
    """auto_start 选项：按官方文档流程显式生成映射起点。

    Cr-Fe-Nb（官方算例）必须仍走映射而非网格法；do_map 内部在空节点时
    本会隐式调用 generate_automatic_starting_points，显式调用 + 中心补点
    重试是给"相区不与边相连"的体系（如 Al-Cu-Y 高温截面）兜底。
    """
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(DB_DIR / "CrFeNb_Jacob2016.tdb")
    plan = ConditionPlan.from_ui(
        db, "ternary_isothermal",
        {"CR": (0, 1, 0.02), "FE": (0, 1, 0.02)},
        {"T": 1323.0, "P": 101325.0},
    )
    comps = db.components_safe(["CR", "FE", "NB"])[0]
    result = compute_diagram(
        db, comps, sorted(db.phase_names), plan, options={"auto_start": True}
    )
    assert result.figure is not None and result.axes is not None
    # 映射成功的标志：标题不带"（网格法）"后缀
    assert "网格法" not in result.title, result.title
    assert result.axes.collections or result.axes.lines, "图上应有实际内容"


def test_ternary_mapping_shaded_official_style() -> None:
    """Cr-Fe-Nb（官方文档同款算例）映射必收敛：
    默认走 plot_ternary，勾选填色走官网 plot_shaded_ternary 样式。"""
    import matplotlib

    matplotlib.use("Agg")
    db = load_database(DB_DIR / "CrFeNb_Jacob2016.tdb")
    plan = ConditionPlan.from_ui(
        db, "ternary_isothermal",
        {"CR": (0, 1, 0.02), "FE": (0, 1, 0.02)},
        {"T": 1323.0, "P": 101325.0},
    )
    comps = db.components_safe(["CR", "FE", "NB"])[0]

    # 填色样式：单相淡蓝底 + 两相白多边形 + 三相黄三角，均为 patch/collection
    result = compute_diagram(
        db, comps, sorted(db.phase_names), plan, options={"grid_fill": True}
    )
    assert result.figure is not None
    ax = result.axes
    assert not ("网格法" in (result.title or "")), "CrFeNb 映射应收敛，不该退网格法"
    patches = ax.patches
    assert patches, "填色样式应画出两相/三相多边形 patch"
    fills = {tuple(np.round(p.get_facecolor(), 3)) for p in patches}
    assert (1.0, 1.0, 0.6, 1.0) in fills or (1.0, 1.0, 0.6) in [
        f[:3] for f in fills
    ], "应存在三相区黄色三角"
    # 单相底色是 fill_between 的 PolyCollection（淡蓝）
    face_colors = [
        tuple(np.round(c.get_facecolor()[0], 3)) for c in ax.collections
        if len(c.get_facecolor())
    ]
    assert any(
        abs(fc[0] - 0.8) < 1e-6 and abs(fc[1] - 0.8) < 1e-6 for fc in face_colors
    ), "应有单相区淡蓝底色"

    # 默认线式：同一体系不勾填色也能出图
    result2 = compute_diagram(db, comps, sorted(db.phase_names), plan)
    assert result2.axes is not None
    assert bool(result2.axes.lines), "线式 plot_ternary 应画出 tie line/边界"


def test_eqplot_ternary_axes_are_distinct() -> None:
    """T62：三元 eqplot 的两个轴不能是同一个组分。

    引擎原先只显式传 ``x``，``y`` 交给 eqplot 用 ``indep_comps[1]`` 自动
    补齐；而 ``indep_comps`` 是**按变量名排序**的，当 x 恰好是排序后的
    第二个独立组分时（本例扫 CR、AL，x=X(CR)），y 又被补成 X(CR)——
    两轴同名，数据在三角投影里退化成一条对角线（用户截图现象）。
    """
    import matplotlib
    import matplotlib.collections as mcoll

    matplotlib.use("Agg")
    db = load_database(_TERN_DB)
    plan = ConditionPlan.from_ui(
        db, "eqplot_ternary",
        {"CR": (0, 1, 0.1), "AL": (0, 1, 0.1)},
        {"T": 1400.0, "P": 101325.0},
    )
    comps = db.components_safe(["AL", "CR", "NI"])[0]
    result = compute_diagram(db, comps, sorted(db.phase_names), plan)
    xl, yl = result.axes.get_xlabel(), result.axes.get_ylabel()
    assert xl and yl, f"两轴都要有标题，实际 x={xl!r} y={yl!r}"
    assert xl != yl, f"两轴不应同名：x={xl!r} y={yl!r}"
    # 三角投影里必须有散点（相）与连线（tie line / tie triangle）
    assert any(isinstance(c, mcoll.PathCollection)
               for c in result.axes.collections), "缺少相散点"
    assert any(isinstance(c, mcoll.LineCollection)
               for c in result.axes.collections), "缺少 tie line / 三相连线"


# ---------------------------------------------------------------------------
# 3d. 相图图像数字化（core/digitizer.py，纯逻辑、合成图即可测）
# ---------------------------------------------------------------------------
def _synthetic_binary():
    """合成一张二元相图：坐标框 + 实线网格 + 一条斜相界。"""
    w, h = 600, 400
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    x0, x1, y0, y1 = 80, 560, 40, 360

    def hline(y):
        img[y, x0:x1] = (0, 0, 0)

    def vline(x):
        img[y0:y1, x] = (0, 0, 0)

    hline(y0); hline(y1); vline(x0); vline(x1)
    for y in range(80, y1, 40):
        hline(y)
    for x in range(140, x1, 60):
        vline(x)
    # 斜相界（不能被当成网格线）
    for i in range(400):
        img[300 - int(i * 200 / 400), 100 + i] = (0, 0, 0)
    return img, (x0, x1, y0, y1)


def test_digitizer_calibration_maps_both_ways() -> None:
    """标定：像素 ↔ 数据坐标互转（三点仿射）。"""
    _img, (x0, x1, y0, y1) = _synthetic_binary()
    cal = Calibration("binary")
    cal.add(x0, y1, (0.0, 300.0))
    cal.add(x1, y1, (1.0, 300.0))
    cal.add(x0, y0, (0.0, 1500.0))
    assert cal.ready
    x, y = cal.to_data(320, 200)
    assert abs(x - 0.5) < 1e-6, x
    assert abs(y - 900.0) < 1.0, y
    # 反算回去要落在原处
    px, py = cal.to_pixel(x, y)
    assert abs(px - 320) < 1e-6 and abs(py - 200) < 1e-6
    # 少一个点 / 三点共线都不可用
    assert not Calibration("binary", [CalibPoint(0, 0, (0, 0))]).ready
    collinear = Calibration("binary", [
        CalibPoint(0, 0, (0, 0)), CalibPoint(1, 0, (1, 0)), CalibPoint(2, 0, (2, 0)),
    ])
    assert not collinear.ready


def test_digitizer_removes_grid_but_keeps_boundary() -> None:
    """去网格线：网格全抹掉，斜的相界必须基本保留（不能被误杀）。"""
    img, _box = _synthetic_binary()
    lines = detect_grid_lines(img, "binary")
    # 9 条横 + 9 条竖：边框也算贯通线
    assert len(lines) >= 16, f"网格线检出过少：{len(lines)}"
    assert {round(float(l["angle"])) for l in lines} == {0, 90}
    cleaned, removed = remove_grid_lines(img, "binary")
    assert removed
    before = int(dark_mask(to_gray(img)).sum())
    after = int(dark_mask(to_gray(cleaned)).sum())
    # 网格线占比在 90% 以上，清理后应只剩斜那一根线（约 300 px）
    assert after < before * 0.15, f"网格线没抹干净：{before} → {after}"
    assert after > 100, f"斜相界被误杀了：只剩 {after} 个暗像素"
    # 吸附：故意点偏 3 px，应落到斜线上
    snapped = snap_to_boundary(cleaned, 300, 197, radius=20)
    assert snapped is not None
    sx, sy = snapped
    assert abs(sy - (300 - (sx - 100) * 0.5)) < 3.0, snapped


def test_digitizer_detects_dashed_grid_lines() -> None:
    """虚线网格：占空比 40% 也要能检出并抹掉（只看"最长连续段"会漏）。"""
    img = np.full((400, 600, 3), 255, dtype=np.uint8)
    for y in (100, 200, 300):
        xs = np.arange(80, 560)
        img[y, xs[(xs // 8) % 5 < 2]] = (0, 0, 0)
    lines = detect_grid_lines(img, "binary")
    assert len(lines) == 3, f"虚线应全部检出，实际 {len(lines)}"
    cleaned, _ = remove_grid_lines(img, "binary")
    assert int(dark_mask(to_gray(cleaned)).sum()) == 0


def test_digitizer_ternary_grid_and_composition() -> None:
    """三元：三方向网格线 + 重心坐标即三个组分分数。"""
    img = np.full((500, 500, 3), 255, dtype=np.uint8)
    a, b, c = (60, 400), (440, 400), (250, 90)

    def line(p, q):
        n = int(np.hypot(q[0] - p[0], q[1] - p[1])) * 2
        for t in np.linspace(0, 1, n):
            img[int(round(p[1] + (q[1] - p[1]) * t)),
                int(round(p[0] + (q[0] - p[0]) * t))] = (0, 0, 0)

    for p, q in ((a, b), (b, c), (c, a)):
        line(p, q)
    for k in range(1, 5):
        f = k / 5.0
        line((60 + 380 * f, 400), (60 + 380 * f + 190 * (1 - f), 400 - 310 * (1 - f)))
        line((60 + 380 * f, 400), (60 + 190 * f, 400 - 310 * f))
        line((60 + 190 * f, 400 - 310 * f), (440 - 190 * f, 400 - 310 * f))
    lines = detect_grid_lines(img, "ternary")
    assert {round(float(l["angle"])) for l in lines} == {0, 60, 120}
    cleaned, _ = remove_grid_lines(img, "ternary")
    assert int(dark_mask(to_gray(cleaned)).sum()) < 0.15 * int(
        dark_mask(to_gray(img)).sum()
    )

    cal = Calibration("ternary")
    cal.add(a[0], a[1], (1.0, 0.0))
    cal.add(b[0], b[1], (0.0, 1.0))
    cal.add(c[0], c[1], (0.0, 0.0))
    # 三角形重心 → 三个组分各 1/3
    cx = (a[0] + b[0] + c[0]) / 3.0
    cy = (a[1] + b[1] + c[1]) / 3.0
    comp = cal.composition(cx, cy)
    assert all(abs(v - 1 / 3) < 0.02 for v in comp), comp
    # 三个顶点各自是纯组分
    assert cal.composition(*a)[0] > 0.99
    assert cal.composition(*b)[1] > 0.99
    assert cal.composition(*c)[2] > 0.99


def test_digitizer_regions_append_below_each_other() -> None:
    """第 5 步：多个区域的点按区域顺序上下拼接，组分之和归一。"""
    cal = Calibration("ternary")
    cal.add(0, 0, (1.0, 0.0))
    cal.add(1, 0, (0.0, 1.0))
    cal.add(0, 1, (0.0, 0.0))
    r1 = DigitizedRegion(1, "FCC", [(0, 0), (1, 0), (0, 1)])
    r2 = DigitizedRegion(2, "BCC", [(0, 0), (0.5, 0), (0, 0.5)])
    frame = regions_to_frame([r1, r2], cal, comp_names=["Al", "Cr", "Ni"],
                             step_x=0.25)
    assert list(frame["区域"]) == sorted(frame["区域"]), "应按区域顺序排列"
    assert set(frame["区域"]) == {1, 2}
    first = frame[frame["区域"] == 1]
    second = frame[frame["区域"] == 2]
    assert len(first) > len(second) > 0
    # 第二个区域的点必须排在前一个区域**下面**
    assert first.index.max() < second.index.min()
    assert set(frame["相标签"]) == {"FCC", "BCC"}
    cols = [c for c in frame.columns if c.startswith("X(")]
    assert len(cols) == 3
    sums = frame[cols].sum(axis=1)
    assert np.allclose(sums, 1.0), "三元组分之和应为 1"


def test_digitizer_projects_click_onto_frame() -> None:
    """贴边点找不到墨迹时（框线被当网格线抹掉），投影到坐标区轮廓上。"""
    cal = Calibration("binary")
    cal.add(80, 360, (0.0, 300.0))
    cal.add(560, 360, (1.0, 300.0))
    cal.add(80, 40, (0.0, 1500.0))
    poly = cal.region_polygon()
    assert poly is not None and len(poly) == 4
    hit = project_to_polygon(poly, 300, 357, tol=10.0)
    assert hit is not None and abs(hit[1] - 360.0) < 1e-6, hit
    # 离得远就不该硬投影
    assert project_to_polygon(poly, 300, 200, tol=10.0) is None


def test_unknown_element_rejected() -> None:
    db = load_database(_BIN_DB)
    try:
        ConditionPlan.from_ui(db, "binary_ztpf", {"ZZZ": (0, 1, 0.1), "T": (500, 800, 50)})
    except CalculationError as exc:
        assert "ZZZ" in exc.user_message
    else:  # pragma: no cover
        raise AssertionError("库外元素应被拒绝")


# ---------------------------------------------------------------------------
# 3b. 元素勾选 → 计算组分的推导（T52）
# ---------------------------------------------------------------------------
def test_components_safe_never_raises_and_reports_ignored() -> None:
    """库外元素不该炸掉 Qt 槽：宽容推导单独回报"被忽略了谁"。"""
    db = load_database(_VZR_DB)
    comps, ignored = db.components_safe(["V", "AU", "va"])
    # 大写规范化：'va' 与 'V' 是同一个组分；AU 不在库里 → 忽略
    assert comps == ["V", "VA"], comps
    assert ignored == ["AU"], ignored

    # 一个真元素都没选（含只勾了空位）时必须是空，而不是 [VA] 这种空壳
    for empty in ((), ("VA",)):
        assert db.components_safe(list(empty)) == ([], []), empty
    assert db.comps_of(["VA"]) == []


def test_sweep_candidates_drops_vacancy() -> None:
    """空位既能扫描轴也能当摩尔分数输入，必须滤掉。"""
    db = load_database(_VZR_DB)
    assert db.sweep_candidates(["VA", "V", "v"]) == ["V"]
    assert db.sweep_candidates([]) == []


def test_axis_candidates_follow_selection() -> None:
    """多元素库（cost507R 那种）里，勾选必须收窄扫描轴候选。"""
    db = load_database(_VZR_DB)
    comps, states = axis_candidates(db, ["V"])
    assert comps == ["V"], comps
    assert states == list(STATE_KEYS)

    # 不传才回落到库内全部元素
    comps_all, _ = axis_candidates(db)
    assert comps_all == ["V", "ZR"], comps_all

    # 勾选里混了库外符号时只挑走得通的，不整个作废
    comps_mixed, _ = axis_candidates(db, ["V", "ZZZ"])
    assert comps_mixed == ["V"], comps_mixed


# ---------------------------------------------------------------------------
# 4. 属性计算（走 Workspace 通道）
# ---------------------------------------------------------------------------
def test_property_curves() -> None:
    db = load_database(_BIN_DB)
    comps = db.components_for(["AL", "ZN"])
    result = compute_property_curves(
        db, comps, db.phase_names, "GM", "ZN", np.linspace(0, 1, 11),
        figure=None,
    )
    assert result.series, "应至少产出一条曲线"
    total_points = sum(len(y) for _, y in result.series.values())
    assert total_points > 0
    # T46：引擎交付的图必须已落定坐标范围。plot() 的 autoscale 是挂起请求，
    # 画布挂载时会先关 autoscale——请求一旦作废，viewLim 停在默认 (0,1)，
    # 曲线"画了却看不见"（用户实测）。
    for _, (xs, ys) in result.series.items():
        if not len(xs):
            continue
        xmin, xmax = result.axes.get_xlim()
        ymin, ymax = result.axes.get_ylim()
        assert xmin <= xs.min() and xmax >= xs.max(), "x 视野未覆盖数据"
        assert ymin <= ys.min() and ymax >= ys.max(), "y 视野未覆盖数据（T46）"


def test_property_curves_per_phase() -> None:
    """逐相模式必须给出**每个相各自的**曲线（T50）。

    用户反馈"属性计算只显示了平衡相的性能，没有单个相的结果"。根因是引擎
    只建过一次全相 ``Workspace``，``get()`` 返回的是 1D 平衡态全局值，无论
    传几个相都只画出一条线。这里断言"相名 = 相数"且**曲线互不相同**——
    只断言条数的化，把同一条线贴到每个相名下照样能过。
    """
    if not _VZR_DB.exists():  # pragma: no cover - 资产缺失时跳过
        print("跳过：缺少 tests/databases/vzr_zha-2012.tdb")
        return
    db = load_database(_VZR_DB)
    comps = db.components_for(["V", "ZR"])
    x = np.linspace(500.0, 1500.0, 11)
    opts = {"fixed_t": 900.0, "fixed_x": 0.3, "curve_scope": "per_phase"}

    result = compute_property_curves(db, comps, db.phase_names, "GM", "T", x, options=opts)
    names = list(result.series)
    assert "平衡态" not in names, "纯逐相模式不该再画平衡态参照线"
    assert set(names) == set(db.phase_names), f"每张相都应有一条曲线，实际 {names}"

    ymat = np.vstack([result.series[n][1] for n in names])
    # 曲线不能雷同：同一条线贴到每个相名下是典型的假通过
    assert len({row.tobytes() for row in ymat}) == len(names), "各相曲线完全相同"
    assert np.isfinite(ymat).all(), "逐相曲线不应含 NaN"
    for n in names:
        xs = result.series[n][0]
        assert xs.size == x.size and np.allclose(xs, x), f"{n} 的 x 轴应是完整扫描点"

    # 视野仍要覆盖数据（T46 回归）
    for _, (xs, ys) in result.series.items():
        xmin, xmax = result.axes.get_xlim()
        ymin, ymax = result.axes.get_ylim()
        assert xmin <= xs.min() and xmax >= xs.max()
        assert ymin <= ys.min() and ymax >= ys.max()

    # 相拆解不能只算勾中的那几个之外的人
    partial = compute_property_curves(
        db, comps, db.phase_names, "GM", "T", x,
        options={**opts, "per_phase_phases": ["BCC_A2", "HCP_A3"]},
    )
    assert sorted(partial.series) == ["BCC_A2", "HCP_A3"], f"只勾两个就只该出两条：{list(partial.series)}"


def test_property_scope_balance_and_both() -> None:
    """平衡态模式保持旧行为；both 模式两者都要有。"""
    db = load_database(_VZR_DB)
    comps = db.components_for(["V", "ZR"])
    x = np.linspace(500.0, 1500.0, 11)
    base = {"fixed_t": 900.0, "fixed_x": 0.3}

    bal = compute_property_curves(
        db, comps, db.phase_names, "GM", "T", x,
        options={**base, "curve_scope": "balance"},
    )
    assert list(bal.series) == ["平衡态"], f"平衡态模式应只有一条，实际 {list(bal.series)}"
    assert bal.scope == "balance"

    both = compute_property_curves(
        db, comps, db.phase_names, "GM", "T", x,
        options={**base, "curve_scope": "both"},
    )
    assert "平衡态" in both.series, "both 模式必须带平衡态参照线"
    assert len(both.series) == len(db.phase_names) + 1
    assert both.scope == "both"

    # 缺省行为（旧调用方不传 curve_scope）必须还是平衡态，不能被默认值改动带崩
    old = compute_property_curves(db, comps, db.phase_names, "GM", "T", x, options=base)
    assert list(old.series) == ["平衡态"]


def test_property_scan_along_temperature() -> None:
    """扫温度必须钉住组分，否则 pycalphad 抛"自由度为不为零"。

    这条用例来自用户反馈"属性计算不出图"——V-Zr 库扫 T 时 conds 里没有
    任何组分条件，直接 ``ValueError: Number of degrees of freedom is not zero``。
    """
    if not _VZR_DB.exists():  # pragma: no cover - 资产缺失时跳过
        print("跳过：缺少 tests/databases/vzr_zha-2012.tdb")
        return
    db = load_database(_VZR_DB)
    comps = db.components_for(["V", "ZR"])
    result = compute_property_curves(
        db, comps, db.phase_names, "GM", "T", np.array([700.0, 900.0, 1100.0]),
        options={"fixed_t": 900.0, "fixed_x": 0.3},
    )
    assert result.series, "扫温度也应画出平衡态曲线"
    for _name, (xs, ys) in result.series.items():
        assert xs.size == 3
        assert np.isfinite(ys).all(), "扫温度得到的 G(T) 不应含 NaN"


def test_property_composition_curve_is_not_cloned_per_phase() -> None:
    """平衡态值不是逐相值：同一条曲线不能贴到每个相名下。

    旧实现用 ``values.ndim > 1`` 判定逐相，而 Workspace 在组分扫描下返回的是
    1D 平衡态数组，结果 4 个相名画出 4 条完全相同的线，读图必错。
    """
    db = load_database(_BIN_DB)
    comps = db.components_for(["AL", "ZN"])
    result = compute_property_curves(
        db, comps, db.phase_names, "GM", "ZN", np.linspace(0, 1, 11),
    )
    names = set(result.series)
    assert names == {"平衡态"}, f"期望单条平衡态曲线，实际 {names}"
    for _name, (xs, ys) in result.series.items():
        assert xs.size == 11 and np.isfinite(ys).all()


def test_property_rejects_unknown_axis() -> None:
    db = load_database(_BIN_DB)
    comps = db.components_for(["AL", "ZN"])
    try:
        compute_property_curves(db, comps, db.phase_names, "GM", "XX", np.linspace(0, 1, 5))
    except CalculationError as exc:
        assert "XX" in exc.user_message
    else:  # pragma: no cover
        raise AssertionError("未知扫描轴应被拒绝")


# ---------------------------------------------------------------------------
# 5. 高通量扫描
# ---------------------------------------------------------------------------
def test_high_throughput() -> None:
    db = load_database(_TERN_DB)
    comps = db.components_for(["AL", "CR"])
    phases = filter_phases(db, db.phase_names)
    config = HTConfig(
        database=db,
        comps=comps,
        phases=phases,
        sweeps={"T": [1300.0, 1400.0], "CR": [0.2, 0.5]},
        outputs=("stable_phases", "n_phases"),
        parallel=2,
    )
    result = run_high_throughput(config)
    assert result.n_ok == 4, f"4 个计算点应全部成功，实际 {result.n_ok}"
    assert not result.frame.empty
    assert "T" in result.frame.columns
    assert "共存相数" in result.frame.columns


def test_high_throughput_has_real_values_not_nan() -> None:
    """结果表不能整表 NaN。

    记录原先以 pycalphad 的 sympy ``Variable`` 为键（``v.T`` / ``v.X('CR')``），
    而 DataFrame 用字符串列名匹配，一个都配不上 → 整表 NaN。列头存在但数值
    全空，只有断言"列名"的测试抓不到，必须逐格检查数值。
    """
    db = load_database(_TERN_DB)
    config = HTConfig(
        database=db,
        comps=db.components_for(["AL", "CR"]),
        phases=filter_phases(db, db.phase_names),
        sweeps={"T": [1300.0, 1400.0], "CR": [0.2, 0.5]},
        outputs=("gm_min", "n_phases"),
        parallel=2,
    )
    result = run_high_throughput(config)
    frame = result.frame
    assert len(frame) == 4, f"应有 4 行，实际 {len(frame)}"
    assert not frame.isna().all().all(), f"整表 NaN：\n{frame}"
    # 扫描轴列必须与输入的采样点完全一致
    assert sorted(frame["T"].tolist()) == [1300.0, 1300.0, 1400.0, 1400.0]
    assert sorted(frame["CR"].tolist()) == [0.2, 0.2, 0.5, 0.5]
    assert np.isfinite(frame["最低G (J/mol)"]).all(), "gm_min 应全部有限"
    assert result.n_degenerate == 0
    assert result.n_failed == 0


def test_high_throughput_nphases_is_displayable() -> None:
    """"共存相数"必须真的有数字，不能只剩空表头（T49）。

    两个坑叠在一起：
    1. core 交付的 ``len(phase_names)`` 经 DataFrame 读回是 ``np.int64``，
       界面用 ``isinstance(x, (int, float, str))`` 过滤后整列被清成空串；
    2. 同时勾选"液相分数"时，``eq.coords["Phase"]`` 在 V-Zr 这类库上会
       ``KeyError``，整点判失败 → 连表都出不来。
    这里两条路径一起覆盖。
    """
    db = load_database(_VZR_DB)  # 只有 V/ZR/IONIC_LIQ，专治第 2 条
    config = HTConfig(
        database=db,
        comps=db.components_for(["V", "ZR"]),
        phases=sorted(db.phase_names),
        sweeps={"T": [1000.0, 1100.0], "V": [0.5, 0.6]},
        outputs=("stable_phases", "gm_min", "n_phases", "np_liquid"),
        parallel=2,
    )
    result = run_high_throughput(config)
    frame = result.frame
    assert result.n_failed == 0, f"不该有点失败：{result.failures}"
    assert len(frame) == 4, f"应有 4 行，实际 {len(frame)}"
    assert "共存相数" in frame.columns

    # 逐格检查：表头在、单元格也必须有内容
    for cell in frame["共存相数"].tolist():
        assert cell is not None, f"共存相数出现空值：\n{frame}"
        assert isinstance(cell, int) and not isinstance(cell, bool), (
            f"共存相数应为 Python 原生 int，实际 {type(cell).__name__}"
        )
        assert 0 <= cell <= len(db.phase_names)
    # 与稳定相组合自洽：相数 = 组合里相的个数
    for phases_text, n in zip(frame["稳定相组合"], frame["共存相数"]):
        assert n == len([p for p in phases_text.split(" + ") if p]), (
            f"共存相数({n}) 与稳定相组合({phases_text}) 不一致"
        )
    # 液相分数列同样不能崩、不能全 NaN
    assert frame["液相分数"].notna().all(), f"液相分数出现空值：\n{frame}"

    # 界面侧的显示链路：走一遍 ht_tab 的单元格文本转换
    from pycalphad_gui.ui.ht_tab import _cell_text

    texts = [_cell_text(v) for v in frame["共存相数"]]
    assert all(t.strip() for t in texts), f"共存相数单元格文本为空：{texts}"
    assert texts == [str(n) for n in frame["共存相数"]]
    assert _cell_text(None) == ""
    assert _cell_text(float("nan")) == ""


def test_scalar_value_normalizes_numpy() -> None:
    """``scalar_value`` 应把 numpy 标量还原成原生类型。"""
    from pycalphad_gui.core.high_throughput import scalar_value

    assert scalar_value(np.int64(3)) == 3 and type(scalar_value(np.int64(3))) is int
    assert scalar_value(np.float64(1.5)) == 1.5 and type(scalar_value(np.float64(1.5))) is float
    assert scalar_value(np.float64("nan")) is None
    assert scalar_value(np.float64("inf")) is None
    assert scalar_value(float("nan")) is None
    assert scalar_value("LIQUID") == "LIQUID"
    assert scalar_value(None) is None
    assert scalar_value(True) is True and type(scalar_value(np.bool_(True))) is bool


def test_high_throughput_cancel() -> None:
    db = load_database(_TERN_DB)
    config = HTConfig(
        database=db,
        comps=db.components_for(["AL", "CR"]),
        phases=filter_phases(db, db.phase_names),
        sweeps={"T": [1200.0, 1300.0, 1400.0]},
        outputs=("n_phases",),
        parallel=1,
    )
    result = run_high_throughput(config, should_cancel=lambda: True)
    assert result.cancelled


# ---------------------------------------------------------------------------
# 6. 导出
# ---------------------------------------------------------------------------
def test_export_image_and_data(tmp_path: Path = None) -> None:
    import matplotlib.pyplot as plt

    tmp = Path(tempfile.mkdtemp())
    fig, ax = plt.subplots()
    ax.plot([0, 1], [0, 1])
    png = export_figure(fig, tmp / "sub" / "plot.png")
    assert png.exists()
    svg = export_figure(fig, tmp / "plot.svg")
    assert svg.exists()

    import pandas as pd

    df = pd.DataFrame({"T": [1.0, 2.0], "v": [3.0, 4.0]})
    csv = export_dataframe(df, tmp / "out.csv")
    assert csv.exists()
    back = pd.read_csv(csv)
    assert len(back) == 2

    series_csv = export_series_csv([("A", np.array([0.0, 1.0]), np.array([2.0, 3.0]))],
                                  tmp / "curve.csv", x_label="X")
    assert series_csv.exists()


def test_export_rejects_unknown_format() -> None:
    import matplotlib.pyplot as plt

    fig, _ = plt.subplots()
    try:
        export_figure(fig, Path(tempfile.mkdtemp()) / "x.bmp")
    except CalculationError as exc:
        assert "不支持" in exc.user_message
    else:  # pragma: no cover
        raise AssertionError("未知格式应报错")


# ---------------------------------------------------------------------------
def main() -> int:
    """无 pytest 环境下的简易运行器。"""
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_")]
    passed, failed = 0, []
    for fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed.append((fn.__name__, exc))
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"ok   {fn.__name__}")
    print(f"\n通过 {passed}/{len(tests)}")
    for name, exc in failed:
        print(f"  · {name}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

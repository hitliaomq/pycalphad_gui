"""相图与属性计算引擎。

把 pycalphad 三条互不兼容的绘图入口（``binplot`` / ``ternplot`` /
``equilibrium + eqplot``）收敛成同一个 ``compute_diagram`` 接口，
对外只暴露 :class:`PlotResult`，让上层不必关心底层走哪条路。

三条路的适用条件已在 :mod:`core.conditions` 中校验，本模块只负责执行与包装。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import matplotlib
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

import pycalphad.variables as v
from pycalphad import equilibrium, eqplot, binplot

from .conditions import ConditionPlan
from .database_manager import LoadedDatabase
from .diagnostics import CalculationError, diagnose, log_exception
from ..config import DIAGRAM_LABELS, PROPERTY_PER_PHASE_KEYS as PER_PHASE_KEYS

#: 进度回调类型：callable(已完成数, 总数, 提示文本)
ProgressCB = Optional[Callable[[int, int, str], None]]


@dataclass
class PlotResult:
    """一次绘制的结果，包含后续交互与导出所需的全部信息。"""

    figure: Figure
    axes: Axes
    diagram_type: str
    title: str
    x_label: str
    y_label: str
    elapsed_s: float
    condition_text: str
    #: 相名 → 分配到的颜色，供图例/标签复用
    phase_colors: Dict[str, str] = field(default_factory=dict)
    #: 原始计算结果（equilibrium 的 xarray 数据集），用于属性查询与导出
    dataset: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def axes_list(self) -> List[Axes]:
        return [self.axes]


# ---------------------------------------------------------------- 轴变量解析
def _compositions_of(plan: ConditionPlan, database: LoadedDatabase) -> List[str]:
    """取出参与扫描的组分（用于 eqplot 的轴指定与标签渲染）。"""
    out = []
    for sweep in plan.sweeps:
        if sweep.is_state:
            continue
        name = (database.resolve(sweep.target) or sweep.target).upper()
        if name not in out:
            out.append(name)
    return out


def _state_of(plan: ConditionPlan) -> str:
    for sweep in plan.sweeps:
        if sweep.is_state:
            return sweep.target.upper()
    return ""


def _pretty(name: str) -> str:
    """把组分名渲染成中文友好的轴标签。"""
    if name in ("T",):
        return "温度 T (K)"
    if name == "P":
        return "压强 P (Pa)"
    if name == "N":
        return "总摩尔数 N (mol)"
    return f"摩尔分数 X({name})"


def _plot_shaded_ternary(
    strategy: Any, x_var: Any, y_var: Any, draw_tielines: bool = True
) -> Axes:
    """官网 ``plot_shaded_ternary`` 样式（基于映射算法结果填色）。

    逻辑与 pycalphad 官方文档 "Plotting using the Mapping API" 一节中的
    ``plot_shaded_ternary`` 示例一致：整幅先铺单相区底色（映射只会在
    tieline 与不变式上覆盖数据，其余必然是单相），再往 triangular 投影
    里加 matplotlib patch——不变式（三相平衡）画三角形、两相区把每条
    tie line 的两端首尾相接成多边形。
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mp
    from pycalphad.mapping.plotting import get_label

    single_phase_color = (0.8, 0.8, 1.0)
    two_phase_color = (1.0, 1.0, 1.0)
    three_phase_color = (1.0, 1.0, 0.6)

    fig, ax = plt.subplots(subplot_kw={"projection": "triangular"})
    ax.fill_between([0, 1], [0, 0], [1, 1], color=single_phase_color)

    # 不变式数据：三相平衡是三角形 patch（带黑色描边）
    for inv in strategy.get_invariant_data(x_var, y_var):
        triangle = mp.Polygon(
            np.array([inv.x, inv.y]).T,
            facecolor=three_phase_color, edgecolor="k",
            linewidth=2, joinstyle="bevel",
        )
        ax.add_patch(triangle)

    # tie line 数据：一条 tie line 的两端点轨迹首尾相接即两相区多边形。
    # 映射起点不同可能把同一两相区切成几段，所以先无描边填多边形、
    # 再单独描线（官方文档同款处理）。
    for tie in strategy.get_tieline_data(x_var, y_var):
        xp = np.concatenate([tie.x[0], tie.x[1][::-1]])
        yp = np.concatenate([tie.y[0], tie.y[1][::-1]])
        polygon = mp.Polygon(np.array([xp, yp]).T, facecolor=two_phase_color)
        ax.add_patch(polygon)
        if draw_tielines:
            for i in range(len(tie.x)):
                ax.plot(tie.x[i], tie.y[i], color="k", linewidth=1)

    ax.set_xlabel(get_label(x_var))
    ax.set_ylabel(get_label(y_var))
    ax.yaxis.label.set_rotation(60)
    ax.yaxis.set_label_coords(x=0.12, y=0.5)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    return ax


def _plot_shaded_binary(strategy: Any, draw_tielines: bool = True) -> Axes:
    """官网 ``plot_shaded_binary`` 样式（基于二元映射结果填色）。

    逻辑与 pycalphad 官方文档 "Plotting using the Mapping API" 一节中的
    ``plot_shaded_binary`` 示例一致：整幅先铺单相区底色（映射只在
    tieline 与不变式上覆盖数据，其余必然是单相），不变式（二元里是线）
    黑色实线描出，tie line 的两端相边界连线之间填两相区颜色。
    """
    import matplotlib.pyplot as plt
    from pycalphad import variables as v
    from pycalphad.mapping.plotting import get_label

    single_phase_color = (0.8, 0.8, 1.0)
    two_phase_color = (1.0, 1.0, 1.0)

    # 成分轴作 x，温度/压强轴作 y（官方文档同款假设）
    x = [var for var in strategy.axis_vars if var not in (v.N, v.P, v.T)][0]
    y = [var for var in strategy.axis_vars if var in (v.N, v.P, v.T)][0]

    fig, ax = plt.subplots(figsize=(7.2, 5.4))
    ax.fill_between(
        strategy.axis_lims[x],
        [strategy.axis_lims[y][0]] * 2,
        [strategy.axis_lims[y][1]] * 2,
        color=single_phase_color,
    )

    # 不变式数据：二元相图里是线，直接黑线画出
    for inv in strategy.get_invariant_data(x, y):
        ax.plot(inv.x, inv.y, color="k", linewidth=1.25, linestyle="-")

    # tie line 数据：两个相各自的边界线 + 两相区填色
    for tie in strategy.get_tieline_data(x, y):
        for xp, yp in zip(tie.x, tie.y):
            ax.plot(xp, yp, color="k", linewidth=1.25, linestyle="-")
        if draw_tielines:
            ax.fill_betweenx(tie.y[0], tie.x[0], tie.x[1], color=two_phase_color)

    ax.set_xlabel(get_label(x))
    ax.set_xlim(strategy.axis_lims[x])
    ax.set_ylabel(get_label(y))
    ax.set_ylim(strategy.axis_lims[y])
    ax.minorticks_on()
    ax.tick_params(axis="both", which="minor", direction="in",
                   bottom=True, top=True, left=True, right=True, pad=7)
    ax.tick_params(axis="both", which="major", direction="in",
                   bottom=True, top=True, left=True, right=True, pad=7)
    return ax


def _render_ternary_grid(
    database: LoadedDatabase,
    comps: Sequence[str],
    phases: Sequence[str],
    conds: Dict[Any, Any],
    x_var: Any,
    y_var: Any,
    progress: ProgressCB = None,
    grid_n: int = 41,
    style: str = "lines",
    draw_tielines: bool = True,
    label_nodes: bool = False,
) -> Axes:
    """网格法绘制三元等温截面（映射算法失败时的兜底）。

    一次向量化 ``equilibrium`` 求解整个三角网格，再按 ``style`` 出图：

    * ``"lines"``（默认）—— Thermo-Calc 经典样式：等边三角形、两相区画
      绿色 tie line 扇形、相边界（溶解度线）按所属相着色。两相点上每相的
      成分端点**恰好落在 binodal 线上**，把相邻网格点的同相端点连起来即
      得到连续的相边界；三角形边界用黑色描边，整张图完全覆盖到边。
    * ``"fill"`` —— 官网 ternplot 风格：单相区按相色填充 + 黑色边界、
      两相区留白，Delaunay 剖分铺满整个三角形、无白色缺口。

    两种样式共享同一次平衡求解，切换样式不重复计算。
    """
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D

    xv = np.linspace(0.0, 1.0, grid_n)
    yv = np.linspace(0.0, 1.0, grid_n)
    grid_conds = {k: val for k, val in conds.items() if k not in (x_var, y_var)}
    grid_conds.setdefault(v.N, 1.0)
    grid_conds[x_var] = xv
    grid_conds[y_var] = yv
    _report(progress, 2, 3, f"网格法：正在求解 {grid_n}×{grid_n} 平衡…")

    eq = equilibrium(database.dbf, list(comps), list(phases), grid_conds)
    # 维度对齐：显式转置成 (x, y, vertex[, component])，挤掉 N/P/T 等单点维度。
    # 顶点维度在不同 pycalphad 版本里叫 vertices / vertex，动态探测。
    vert_dim = next(d for d in eq["Phase"].dims if "vertex" in str(d))
    xdim, ydim = str(x_var), str(y_var)

    def _grid_array(name: str, dtype: str) -> np.ndarray:
        da = eq[name].squeeze(drop=True)
        order = [xdim, ydim, vert_dim] + (
            ["component"] if "component" in da.dims else []
        )
        return np.asarray(da.transpose(*order).values, dtype=dtype)

    ph = _grid_array("Phase", "U")
    npv = _grid_array("NP", float)
    x_elem = str(x_var).replace("X_", "").upper()
    y_elem = str(y_var).replace("X_", "").upper()

    # 每个网格点 → [(相名, 顶点序号), ...]（NP 显著大于 0 的稳定相）。
    # 注意不按相名去重：混溶隙（如 B2+B2）会让同一相占据两个顶点，
    # 各顶点成分不同，去重会丢掉混溶隙的 tie line。
    stable: List[List[List[Tuple[str, int]]]] = [
        [[] for _ in range(grid_n)] for _ in range(grid_n)
    ]
    for i in range(grid_n):
        for j in range(grid_n):
            if xv[i] + yv[j] > 1.0 + 1e-9:
                continue  # 三角形外的方格点无效
            for k, (p, frac) in enumerate(zip(ph[i, j], npv[i, j])):
                p = str(p)
                if p and p != "" and float(frac) > 1e-6:
                    stable[i][j].append((p, k))

    # tab20 只有 20 色，大体系的相轻松超过它；tab20b/c 再各补 20 个
    palette = [
        cm(k)
        for cm in (matplotlib.colormaps["tab20"], matplotlib.colormaps["tab20b"],
                   matplotlib.colormaps["tab20c"])
        for k in range(20)
    ]

    if style == "fill":
        return _ternary_fill_view(
            stable, xv, yv, palette, grid_n, x_var, y_var, plt
        )
    return _ternary_lines_view(
        stable, ph, npv, eq, _grid_array, x_elem, y_elem,
        xv, yv, palette, grid_n, x_var, y_var,
        draw_tielines, label_nodes, plt,
    )


#: 等边三元投影常数：√3/2
_TERN_SQ3_2 = np.sqrt(3.0) / 2.0


def _ternary_project(px: float, py: float) -> Tuple[float, float]:
    """成分 (X(横轴元素), X(纵轴元素)) → 等边三角形直角坐标。

    底边自左向右为横轴元素 0→1，左边自下而上为纵轴元素 0→1，
    左下角顶点是第三个元素（1 − X₁ − X₂）。"""
    return px + 0.5 * py, _TERN_SQ3_2 * py


def _make_ternary_axes(plt, x_elem: str, y_elem: str) -> Tuple[Figure, Axes]:
    """等边三元坐标系骨架：黑描边 + 手绘刻度 + 紧贴坐标轴的轴标题。

    经典线式与官网填充式两种样式共用，保证观感一致；
    ``axis off`` 后所有元素手绘，避免 matplotlib 普通坐标轴把标签甩得很远。"""
    fig = plt.figure(figsize=(8.2, 6.0))
    ax = fig.add_subplot()
    ax.set_axis_off()
    ax.set_aspect("equal")
    ax.set_xlim(-0.10, 1.10)
    ax.set_ylim(-0.14, 1.00)
    P0, P1, P2 = (0.0, 0.0), (1.0, 0.0), (0.5, _TERN_SQ3_2)
    ax.plot(
        [P0[0], P1[0], P2[0], P0[0]],
        [P0[1], P1[1], P2[1], P0[1]],
        color="black", linewidth=1.3, zorder=4,
    )
    for t in np.linspace(0.0, 1.0, 11):
        # 底边刻度：横轴元素
        ax.plot([t, t], [0.0, -0.015], color="black", linewidth=0.8, zorder=4)
        ax.text(t, -0.04, f"{t:.1f}", ha="center", va="top", fontsize=7)
        # 左边刻度：纵轴元素（外法向 (-√3/2, 1/2)）
        px, py = t * P2[0], t * P2[1]
        ax.plot(
            [px, px - 0.015 * _TERN_SQ3_2], [py, py + 0.015 * 0.5],
            color="black", linewidth=0.8, zorder=4,
        )
        ax.text(
            px - 0.035 * _TERN_SQ3_2, py + 0.035 * 0.5, f"{t:.1f}",
            ha="right", va="center", fontsize=7,
        )
    # 轴标题紧贴坐标轴：底边居中在下，左边沿 60° 斜放
    ax.text(0.5, -0.095, _pretty(x_elem), ha="center", va="top", fontsize=9)
    ax.text(
        0.5 * P2[0] - 0.085 * _TERN_SQ3_2, 0.5 * P2[1] + 0.085 * 0.5,
        _pretty(y_elem), ha="center", va="center", rotation=60, fontsize=9,
    )
    return fig, ax


def _ternary_fill_view(
    stable, xv, yv, palette, grid_n, x_var, y_var, plt
) -> Axes:
    """官网 ternplot 风格：单相区按相色填充 + 黑色边界，两相区留白。

    对全部有效格点做 Delaunay 三角剖分——(0,0)/(1,0)/(0,1) 三个顶点都是
    网格节点，凸包恰为整个成分三角形，因此**铺满无缺口**（旧版方块
    marker 在边缘留白的问题根源在此）。只有三个节点同属一个单相的
    三角形才着色，着色三角形的外边缘描黑；区域边界落在网格单元中点，
    锯齿比格点标记细一半。若整个截面没有任何单相区（极端情况），
    退化为按相组合铺色。
    """
    from matplotlib.collections import LineCollection, PolyCollection
    from matplotlib.lines import Line2D
    from matplotlib.tri import Triangulation

    x_elem = str(x_var).replace("X_", "")
    y_elem = str(y_var).replace("X_", "")
    fig, ax = _make_ternary_axes(plt, x_elem, y_elem)

    pts_list: List[Tuple[float, float]] = []
    node_phase: List[Optional[str]] = []  # 单相节点的相名，否则 None
    node_label: List[Tuple[str, ...]] = []  # 每节点的相组合（按名去重）
    for i in range(grid_n):
        for j in range(grid_n):
            if xv[i] + yv[j] > 1.0 + 1e-9 or not stable[i][j]:
                continue
            names = {name for name, _ in stable[i][j]}
            node_phase.append(next(iter(names)) if len(names) == 1 else None)
            node_label.append(tuple(sorted(names)))
            pts_list.append(_ternary_project(float(xv[i]), float(yv[j])))
    if not pts_list:
        raise CalculationError(
            "网格法没有求得任何有效平衡",
            "请检查固定温度是否在数据库有效区间内，或勾选更多相",
        )
    pts = np.asarray(pts_list)
    triang = Triangulation(pts[:, 0], pts[:, 1])
    tri_verts = triang.triangles

    # 着色身份：正常情况是单相相名；全无单相区时退化为相组合标签
    seen_phases = sorted({p for p in node_phase if p})
    phase_colors = {p: palette[k % len(palette)] for k, p in enumerate(seen_phases)}
    combo_labels = sorted(set(node_label))
    combo_colors = {lb: palette[k % len(palette)] for k, lb in enumerate(combo_labels)}
    use_combo_fallback = not seen_phases

    face_cols: List[str] = []
    edge_owners: Dict[Tuple[int, int], List[str]] = {}

    def _edge_key(a: int, b: int) -> Tuple[int, int]:
        return (a, b) if a < b else (b, a)

    for t in tri_verts:
        names = [node_phase[k] for k in t]
        if not use_combo_fallback and names[0] is not None and names.count(names[0]) == 3:
            col: Optional[str] = phase_colors[names[0]]
            identity = names[0]
        elif use_combo_fallback:
            col = combo_colors[node_label[t[0]]]
            identity = "+".join(node_label[t[0]])
        else:
            col, identity = None, None
        face_cols.append(col if col else "none")
        if col is not None:
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                edge_owners.setdefault(_edge_key(a, b), []).append(identity)

    ax.add_collection(PolyCollection(
        [pts[t] for t in tri_verts], facecolors=face_cols,
        edgecolors="none", zorder=1,
    ))

    # 着色区域的外边缘描黑：一条边只被一个着色三角形拥有，或两侧
    # 着色身份不同（两个单相区直接相接），都是边界
    bnd = [
        (pts[a], pts[b])
        for (a, b), owners in edge_owners.items()
        if len(owners) == 1 or len(set(owners)) == 2
    ]
    if bnd:
        ax.add_collection(LineCollection(
            bnd, colors=["black"], linewidths=1.0, zorder=3,
        ))

    if use_combo_fallback:
        handles = [
            Line2D([], [], marker="s", linestyle="", markersize=9,
                   color=combo_colors[lb], label=" + ".join(lb))
            for lb in combo_labels
        ]
    else:
        handles = [
            Line2D([], [], marker="s", linestyle="", markersize=9,
                   color=phase_colors[p], label=p)
            for p in seen_phases
        ]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.02, 0.5),
              fontsize=8, title="相")
    return ax


def _ternary_lines_view(
    stable, ph, npv, eq, grid_array, x_elem, y_elem,
    xv, yv, palette, grid_n, x_var, y_var,
    draw_tielines: bool, label_nodes: bool, plt,
) -> Axes:
    """Thermo-Calc 经典样式：tie line 扇形 + 相色边界线，等边三角形投影。"""
    from matplotlib.collections import LineCollection
    from matplotlib.lines import Line2D

    # 每相端点成分：X 维度按 component 取出扫描轴两个元素的摩尔分数
    comp_names = [str(c).upper() for c in eq["X"].coords["component"].values]
    if x_elem not in comp_names or y_elem not in comp_names:
        raise CalculationError(
            "网格法无法在平衡结果中找到扫描组分的成分数据",
            f"扫描轴 {x_elem}/{y_elem}，结果成分维度：{comp_names}",
        )
    xall = grid_array("X", float)
    cx = xall[..., comp_names.index(x_elem)]  # X(横轴元素) per (i, j, vertex)
    cy = xall[..., comp_names.index(y_elem)]  # X(纵轴元素)

    unique_phases = sorted({name for row in stable for cell in row for name, _ in cell})
    if not unique_phases:
        raise CalculationError(
            "网格法没有求得任何有效平衡",
            "请检查固定温度是否在数据库有效区间内，或勾选更多相",
        )
    colors = {p: palette[k % len(palette)] for k, p in enumerate(unique_phases)}

    _proj = _ternary_project

    def _endpoint(i: int, j: int, k: int) -> Optional[Tuple[float, float]]:
        """取顶点 (i,j,k) 的投影坐标；端点滑出三角形（数值误差）则丢弃。"""
        px, py = float(cx[i, j, k]), float(cy[i, j, k])
        if not (np.isfinite(px) and np.isfinite(py)):
            return None
        if px < -1e-6 or py < -1e-6 or px + py > 1.0 + 1e-6:
            return None
        return _proj(max(px, 0.0), max(py, 0.0))

    def _grid_point(i: int, j: int) -> Tuple[float, float]:
        return _proj(float(xv[i]), float(yv[j]))

    def _on_edge(i: int, j: int) -> bool:
        return (
            xv[i] < 1e-9 or yv[j] < 1e-9 or xv[i] + yv[j] > 1.0 - 1e-9
        )

    fig, ax = _make_ternary_axes(plt, x_elem, y_elem)

    # 1) tie line 扇形：两相点连两端点成分，三相点连三条边（绿色细线）
    if draw_tielines:
        tie_segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        for i in range(grid_n):
            for j in range(grid_n):
                entries = stable[i][j]
                if len(entries) < 2:
                    continue
                pts = [_endpoint(i, j, k) for _, k in entries]
                for a in range(len(pts)):
                    for b in range(a + 1, len(pts)):
                        if pts[a] is None or pts[b] is None:
                            continue
                        tie_segs.append((pts[a], pts[b]))
        if tie_segs:
            ax.add_collection(LineCollection(
                tie_segs, colors=["#2ca02c"], linewidths=0.35,
                alpha=0.55, zorder=1,
            ))

    # 2) 相边界线（按所属相着色）：相邻格点的同相端点相连。
    #    两相/三相点的端点恰好落在 binodal 上，连出来即是溶解度线；
    #    单相区内部不画（保持白底），只有贴着三角形边缘的同相单相点
    #    才沿边描一条相色线。
    bnd_segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    bnd_cols: List[str] = []

    def _label(i: int, j: int) -> Tuple[str, ...]:
        """相组合标签（按相名去重：混溶隙 B2+B2 在分区逻辑里算一个 B2）。"""
        return tuple(sorted({name for name, _ in stable[i][j]}))

    def _name_points(i: int, j: int, name: str) -> List[Tuple[float, float]]:
        """某相在格点 (i,j) 的全部端点投影；单相点即格点本身。"""
        if len(stable[i][j]) == 1 and stable[i][j][0][0] == name:
            return [_grid_point(i, j)]
        pts = [_endpoint(i, j, k) for nm, k in stable[i][j] if nm == name]
        return [p for p in pts if p is not None]

    def _match_pairs(
        pts_a: List[Tuple[float, float]],
        pts_b: List[Tuple[float, float]],
    ):
        """贪心最近邻配对：同一相可能占据多个顶点（混溶隙），而 pycalphad
        的顶点顺序在相邻格点间可能交换，按名字取索引会连线交叉，
        必须按空间就近配对。"""
        used: set = set()
        for pa in pts_a:
            best, bd = None, float("inf")
            for idx, pb in enumerate(pts_b):
                if idx in used:
                    continue
                d = (pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2
                if d < bd:
                    bd, best = d, idx
            if best is not None:
                used.add(best)
                yield pa, pts_b[best]

    for i in range(grid_n):
        for j in range(grid_n):
            here = stable[i][j]
            if not here:
                continue
            la = _label(i, j)
            for di, dj in ((1, 0), (0, 1)):
                i2, j2 = i + di, j + dj
                if i2 >= grid_n or j2 >= grid_n or not stable[i2][j2]:
                    continue
                there = stable[i2][j2]
                lb = _label(i2, j2)
                if la != lb:
                    # 不同相组合相邻：单相区的边界就是对面两相区的 binodal
                    # （已由该区的同相端点描出），再从单相格点连"短棒"只会
                    # 叠出阶梯状粗带，跳过。
                    continue
                if len(here) == 1:
                    # 同一单相相区内部：不画。仅沿三角形边缘描相色边线
                    if _on_edge(i, j) and _on_edge(i2, j2):
                        bnd_segs.append((_grid_point(i, j), _grid_point(i2, j2)))
                        bnd_cols.append(colors[here[0][0]])
                    continue
                # 同一多相组合内部（含混溶隙 B2+B2 与同名单相的交界）：
                # 同相端点就近配对相连
                here_names = {name for name, _ in here}
                there_names = {name for name, _ in there}
                for name in here_names & there_names:
                    pa_list = _name_points(i, j, name)
                    pb_list = _name_points(i2, j2, name)
                    for pa, pb in _match_pairs(pa_list, pb_list):
                        bnd_segs.append((pa, pb))
                        bnd_cols.append(colors[name])
    if bnd_segs:
        ax.add_collection(LineCollection(
            bnd_segs, colors=bnd_cols, linewidths=1.1, alpha=0.9, zorder=3,
        ))

    # 3) 相区标注（可选）：单相区质心处写相名
    if label_nodes:
        acc: Dict[str, List[Tuple[float, float]]] = {}
        for i in range(grid_n):
            for j in range(grid_n):
                if len(stable[i][j]) == 1:
                    acc.setdefault(stable[i][j][0][0], []).append(
                        _grid_point(i, j)
                    )
        for name, pts in acc.items():
            if len(pts) < 3:
                continue  # 太小的角落不标，避免文字重叠
            mx = float(np.mean([p[0] for p in pts]))
            my = float(np.mean([p[1] for p in pts]))
            # 贴边的薄相区质心可能落到坐标轴上，钳回三角形内
            mx = min(max(mx, 0.08), 0.92)
            my = min(max(my, 0.04), _TERN_SQ3_2 - 0.04)
            ax.text(mx, my, name, ha="center", va="center",
                    fontsize=8, color=colors[name], zorder=5,
                    bbox=dict(boxstyle="round,pad=0.15", fc="white",
                              ec="none", alpha=0.75))

    # 4) 图例：相名 → 边界线颜色
    handles = [
        Line2D([], [], marker="s", linestyle="", markersize=9,
               color=colors[p], label=p)
        for p in unique_phases
    ]
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.02, 0.5),
              fontsize=8, title="相")
    return ax


# ---------------------------------------------------------------- 执行
def compute_diagram(
    database: LoadedDatabase,
    comps: Sequence[str],
    phases: Sequence[str],
    plan: ConditionPlan,
    options: Optional[Dict[str, Any]] = None,
    figure: Optional[Figure] = None,
    progress: ProgressCB = None,
) -> PlotResult:
    """计算并绘制相图。

    Parameters
    ----------
    database
        已加载的数据库。
    comps / phases
        计算组分与参与计算的相（应已由 UI 过滤）。
    plan
        条件计划，见 :class:`~core.conditions.ConditionPlan`。
    options
        绘图开关：``tielines``、``label_nodes``、``figsize`` 等。
    figure
        复用的画布；为 None 时新建。
    progress
        可选进度回调。

    Raises
    ------
    CalculationError
        计算失败或条件不适用。
    """
    options = options or {}
    t0 = time.perf_counter()
    kind = plan.diagram_type

    try:
        # binplot（二元 T–X / ZPFE）内部只认 (start, stop, step) 区间条件，
        # 传离散数组会报 "need at least one array to concatenate"。
        conds = (
            plan.build_ranges(database)
            if kind in ("binary_ztpf", "step", "isopleth")
            else plan.build(database)
        )

        if kind == "binary_ztpf":
            _report(progress, 1, 3, "正在计算二元 ZPFE 相图…")
            ax = None
            if bool(options.get("grid_fill")):
                # 勾选填色：按官方 "Plotting using the Mapping API" 的
                # plot_shaded_binary 配方走 BinaryStrategy 映射 + 填色；
                # 映射失败或无结果时退回 binplot（下方兜底）
                try:
                    from pycalphad.mapping import BinaryStrategy

                    strategy = BinaryStrategy(
                        database.dbf, list(comps), list(phases), conds
                    )
                    strategy.do_map()
                    if strategy.zpf_lines:
                        ax = _plot_shaded_binary(
                            strategy,
                            draw_tielines=bool(options.get("tielines", True)),
                        )
                except Exception as exc:  # noqa: BLE001 - 填色失败退 binplot
                    log_exception(exc, "二元映射填色失败，改用 binplot")
                    ax = None
            if ax is None:
                ax = binplot(
                    database.dbf,
                    list(comps),
                    list(phases),
                    conds,
                    tielines=bool(options.get("tielines", True)),
                    label_nodes=bool(options.get("label_nodes", False)),
                )
            x_name = next(
                (s.target.upper() for s in plan.sweeps if not s.is_state), comps[0]
            )
            s_name = _state_of(plan)
            title = f"{DIAGRAM_LABELS[kind]} — {database.name}"
            x_label = _pretty(x_name)
            y_label = _pretty(s_name)
            figure = ax.get_figure()

        elif kind == "ternary_isothermal":
            _report(progress, 1, 3, "正在计算三元等温等压截面…")
            comp_names = _compositions_of(plan, database)
            if len(comp_names) < 2:
                raise CalculationError(
                    "三元等温截面需要两个组分扫描轴",
                    f"当前只有 {comp_names}",
                )
            x_var = v.X(comp_names[0])
            y_var = v.X(comp_names[1])
            # pycalphad 的 TernaryStrategy 要求一个"不在扫描轴上的真元素"，
            # 其成分由 N=1 隐式确定为 1 - x - y。只勾两个真元素（第三组分是 VA）
            # 时它会直接 IndexError，这里提前拦下并说人话。
            axis_species = {comp_names[0].upper(), comp_names[1].upper()}
            third = [c for c in comps if c.upper() not in axis_species and c.upper() != "VA"]
            if not third:
                raise CalculationError(
                    "三元等温截面至少需要三个元素：两个作扫描轴，第三个决定截面位置",
                    f"当前勾选的真元素只有 {sorted(axis_species)}——请回周期表补选第三个元素",
                )
            # T57：pycalphad 0.11 的步进映射在本库这类体系上可能全军覆没
            # （起点搜索 0 节点），plot_ternary 会在空的 tie line 上直接崩。
            # 因此不走 ternplot 一步到位，而是先跑映射、看 tie line 是否为空，
            # 空则退回网格法绘制；映射本身抛异常也退回网格法。
            # T61：TernaryStrategy 对条件值形式敏感——X 传 np.linspace 全量
            # 数组会 0 节点收场（连 Cr-Fe-Nb 官方算例都复现），必须传
            # (start, stop, step) 三元组；此前 cost507R"映射全军覆没"实为
            # 此坑。标量条件（T/P/N）不受影响。
            map_conds: Dict[Any, Any] = {}
            for ckey, cval in conds.items():
                if isinstance(cval, np.ndarray) and cval.size >= 2:
                    map_conds[ckey] = (
                        float(cval[0]), float(cval[-1]),
                        float(cval[1]) - float(cval[0]),
                    )
                else:
                    map_conds[ckey] = cval
            auto_start = bool(options.get("auto_start"))
            try:
                from pycalphad.mapping import TernaryStrategy
                from pycalphad.mapping.plotting import plot_ternary

                strategy = TernaryStrategy(database.dbf, list(comps), list(phases), map_conds)
                if auto_start:
                    # 官方文档流程：显式沿三条边步进搜起点。do_map 内部在
                    # 空节点时也会做同一步，这里显式化是为了下面的重试语义
                    strategy.generate_automatic_starting_points()
                strategy.do_map()
                tieline_data = strategy.get_tieline_data(x_var, y_var)
                #if (
                #    auto_start
                #    and (tieline_data is None or len(tieline_data) == 0)
                #    and isinstance(map_conds.get(x_var), tuple)
                #    and isinstance(map_conds.get(y_var), tuple)
                #):
                if auto_start:
                    # 起点只沿三条边搜：相区不与边相连的体系（官方文档的
                    # Al-Cu-Y 高温截面同款场景）会一无所获——照文档"补自
                    # 定义起点"的思路，在三角形内部撒几个点再映射一次
                    lo_x, hi_x, _ = map_conds[x_var]
                    lo_y, hi_y, _ = map_conds[y_var]
                    for fx, fy in ((1 / 3, 1 / 3), (0.5, 0.5), (0.25, 0.5), (0.5, 0.25)):
                        try:
                            node_conds = dict(map_conds)
                            node_conds[x_var] = lo_x + (hi_x - lo_x) * fx
                            node_conds[y_var] = lo_y + (hi_y - lo_y) * fy
                            strategy.add_nodes_from_conditions(node_conds)
                        except Exception:  # noqa: BLE001 - 单个补点失败继续下一个
                            pass
                    strategy.do_map()
                    tieline_data = strategy.get_tieline_data(x_var, y_var)
            except Exception as exc:  # noqa: BLE001 - 映射失败不整体失败，退网格
                log_exception(exc, "三元映射算法失败，改用网格法")
                tieline_data = None
            if tieline_data is not None and len(tieline_data):
                _report(progress, 2, 3, "正在绘制三元相图…")
                if bool(options.get("grid_fill")):
                    # 官网 plot_shaded_ternary 样式：映射数据直接填色
                    ax = _plot_shaded_ternary(
                        strategy, x_var, y_var,
                        draw_tielines=bool(options.get("tielines", True)),
                    )
                else:
                    ax = plot_ternary(
                        strategy, x_var, y_var,
                        tielines=bool(options.get("tielines", True)),
                        label_nodes=bool(options.get("label_nodes", False)),
                    )
                method_note = ""
            else:
                _report(progress, 2, 3, "映射未收敛，改用网格法求解等温截面…")
                ax = _render_ternary_grid(
                    database, comps, phases, conds, x_var, y_var, progress,
                    style=("fill" if bool(options.get("grid_fill")) else "lines"),
                    draw_tielines=bool(options.get("tielines", True)),
                    label_nodes=bool(options.get("label_nodes", False)),
                )
                method_note = "（网格法）"
            title = f"{DIAGRAM_LABELS[kind]}{method_note} — {database.name}"
            x_label = _pretty(comp_names[0])
            y_label = _pretty(comp_names[1])
            figure = ax.get_figure()

        elif kind == "step":
            # 官方 Mapping API 的 Step plotting：沿单轴步进，
            # plot_step 默认画相分数 vs 扫描轴
            _report(progress, 1, 3, "正在计算 Step 图（单轴步进）…")
            from pycalphad.mapping import StepStrategy
            from pycalphad.mapping.plotting import plot_step

            strategy = StepStrategy(database.dbf, list(comps), list(phases), conds)
            strategy.do_map()
            _report(progress, 2, 3, "正在绘制 Step 图…")
            # y 轴内容可选：相分数（默认）/ 相中元素含量 / 任意属性量
            # （官方文档 plot_step(step, x=..., y=v.X('AL') / 'CPM')）
            # ax 预建自纯 Figure：plot_step 内部走 pyplot，在工作线程里
            # 碰 pyplot 的全局图形管理器会直接 abort（T72）
            fig = Figure(figsize=tuple(options.get("figsize", (7, 5))))
            ax = fig.subplots()
            axis_var = next(
                (k for k, vv in conds.items() if isinstance(vv, tuple)), None
            )
            step_y = options.get("step_y", "fraction")
            if isinstance(step_y, str) or step_y == "fraction":
                plot_step(strategy, x=axis_var, ax=ax)
            elif isinstance(step_y, (tuple, list)) and step_y and step_y[0] == "x":
                plot_step(strategy, x=axis_var, y=v.X(str(step_y[1]).upper()), ax=ax)
            elif isinstance(step_y, (tuple, list)) and len(step_y) == 2:
                plot_step(strategy, x=axis_var, y=str(step_y[1]), ax=ax)
            else:
                plot_step(strategy, x=axis_var, ax=ax)
            swept = plan.sweeps[0]
            x_label = _pretty(swept.target)
            y_label = "相分数"
            title = f"{DIAGRAM_LABELS[kind]} — {database.name}"
            figure = ax.get_figure()

        elif kind == "isopleth":
            # 官方 Mapping API 的 Isopleth plotting：多组分垂直截面，
            # 1 个组分扫描 + 1 个温度扫描，剩余成分用固定成分钉住
            _report(progress, 1, 3, "正在计算 Isopleth 垂直截面…")
            from pycalphad.mapping import IsoplethStrategy
            from pycalphad.mapping.plotting import plot_isopleth

            strategy = IsoplethStrategy(database.dbf, list(comps), list(phases), conds)
            strategy.do_map()
            _report(progress, 2, 3, "正在绘制 Isopleth…")
            fig = Figure(figsize=tuple(options.get("figsize", (7, 5))))
            ax = fig.subplots()
            plot_isopleth(strategy, ax=ax)
            comp_sweep = next(s for s in plan.sweeps if not s.is_state)
            state_sweep = next(s for s in plan.sweeps if s.is_state)
            x_label = _pretty(comp_sweep.target)
            y_label = _pretty(state_sweep.target)
            title = f"{DIAGRAM_LABELS[kind]} — {database.name}"
            figure = ax.get_figure()

        elif kind in ("eqplot_binary", "eqplot_ternary"):
            _report(progress, 1, 3, "正在求解平衡态…")
            eq = equilibrium(database.dbf, list(comps), list(phases), conds)
            _report(progress, 2, 3, "正在绘制相区…")
            # eqplot 的 x/y 必须显式给出（ARCHITECTURE T1/T62）：
            # x 一定要是组分。若只给 x 不给 y，eqplot 会用 indep_comps[1]
            # 补齐——而 indep_comps 是**按变量名排序**的，当 x 恰好等于
            # 排序后的第二个独立组分时（如扫 V 与 Al，x 传 X(V)），
            # y 又被补成 X(V)，两轴同名 → 数据退化成一条对角线。
            comp_names = _compositions_of(plan, database)
            if kind == "eqplot_ternary":
                if len(comp_names) < 2:
                    raise CalculationError(
                        "三元平衡态需要两个组分扫描轴",
                        f"当前只有 {comp_names}",
                    )
                x_arg = v.X(comp_names[0])
                y_arg = v.X(comp_names[1])
            else:
                x_arg = v.X(comp_names[0]) if comp_names else None
                pot = next(
                    (s.target.upper() for s in plan.sweeps
                     if s.is_state and s.target.upper() in ("T", "P")),
                    None,
                )
                y_arg = v.T if pot == "T" else (v.P if pot == "P" else None)
            ax = eqplot(
                eq,
                x=x_arg,
                y=y_arg,
                tielines=bool(options.get("tielines", True)),
            )
            if kind == "eqplot_ternary":
                # 三元投影的排版微调：eqplot 默认把 y 轴标签放在
                # (0.275 - 1/figwidth, 0.5)（axes 坐标），图小的时候正好
                # 压在左侧刻度数字上。这里放大画布并把标签移到三角形外侧，
                # 同时收小刻度字号，避免底部 0.0~1.0 挤成一团。
                ax.figure.set_size_inches(8.6, 6.4)
                ax.tick_params(axis="both", which="major", labelsize=10)
                ax.yaxis.label.set_rotation(60)
                ax.yaxis.label.set_va("center")
                ax.yaxis.set_label_coords(-0.02, 0.45)
                ax.xaxis.label.set_fontsize(14)
                ax.yaxis.label.set_fontsize(14)
                ax.set_xlabel(ax.get_xlabel(), labelpad=12)
            dataset = eq
            title = f"{DIAGRAM_LABELS[kind]} — {database.name}"
            x_label = ax.get_xlabel() or _pretty(comp_names[0] if comp_names else "")
            y_label = ax.get_ylabel() or "温度 T (K)"
            figure = ax.get_figure()
            _report(progress, 3, 3, "完成")

        else:  # pragma: no cover - 前置校验已拦截
            raise CalculationError(f"不支持的相图类型：{kind}")

        elapsed = time.perf_counter() - t0
        return PlotResult(
            figure=figure,
            axes=ax,
            diagram_type=kind,
            title=title,
            x_label=x_label,
            y_label=y_label,
            elapsed_s=elapsed,
            condition_text=plan.describe(),
            dataset=dataset if kind.startswith("eqplot") else None,
            extra={"comps": list(comps), "phases": list(phases)},
        )

    except CalculationError:
        raise
    except Exception as exc:  # noqa: BLE001 - 引擎边界，统一翻译
        log_exception(exc, f"绘制 {kind} 相图")
        translated = diagnose(exc, DIAGRAM_LABELS.get(kind, "相图"))
        if progress is not None:
            try:
                progress(0, 0, f"失败：{translated.user_message}")
            except Exception:  # pragma: no cover - 回调本身出错不应掩盖主异常
                pass
        raise translated from exc


# ---------------------------------------------------------------- 属性计算
@dataclass
class PropertyResult:
    """属性曲线的绘制结果。

    ``series`` 形如 ``{"FCC_A1": (x_array, y_array), ...}``，
    ``stable`` 是全局平衡下的曲线（若有）。
    """

    figure: Figure
    axes: Axes
    series: Dict[str, Tuple[np.ndarray, np.ndarray]]
    property_name: str
    elapsed_s: float
    condition_text: str
    x_label: str
    y_label: str
    title: str
    #: 曲线来源：``per_phase`` / ``balance`` / ``both``
    scope: str = "balance"
    #: 逐相计算中被跳过（无有限值 / 与条件冲突）的相名，UI 需如实告知用户
    skipped_phases: List[str] = field(default_factory=list)

    def to_table(self) -> Tuple[List[str], np.ndarray]:
        """导出用：返回 (列名, 数据矩阵)。"""
        names = list(self.series.keys())
        cols = [self.series[n][0] for n in names]
        cols += [self.series[n][1] for n in names]
        width = max(len(c) for c in cols) if cols else 0
        matrix = np.zeros((width, len(cols)))
        for i, c in enumerate(cols):
            matrix[: len(c), i] = c
        return names, matrix


def _as_curve_columns(values: np.ndarray, n_points: int) -> List[np.ndarray]:
    """把 Workspace 返回的属性值规整成若干条长度 = n_points 的 1-D 曲线。

    多数属性是 1-D；带相多重性时（如 B2#1 / B2#2）返回 2-D，两个维度
    一个是"份数"一个是"扫描点"，以哪个轴对得上扫描点数来定方向。
    """
    arr = np.atleast_1d(np.asarray(values, dtype=float))
    if arr.ndim == 1:
        return [arr] if arr.size == n_points else []
    if arr.ndim == 2:
        if arr.shape[1] == n_points:  # 每行一条曲线
            return [arr[i] for i in range(arr.shape[0])]
        if arr.shape[0] == n_points:  # 每列一条曲线
            return [arr[:, j] for j in range(arr.shape[1])]
    return []


def _property_conds(
    database: LoadedDatabase,
    x_target: str,
    x_arr: np.ndarray,
    fixed_t: float,
    fixed_x: float,
    fixed_comps: Optional[Dict[str, float]] = None,
) -> Dict[Any, Any]:
    """构造属性计算的 conds。

    两条扫描轴的约束完全不同，混淆是属性页不出图的主因（T43）：

    * **扫组分** —— ``X(组分)`` 取扫描点，T / P / N 取固定值；
    * **扫温度** —— T 取扫描点，但**必须把某个组分的摩尔分数钉死**，否则
      体系自由度不为零，pycalphad 直接抛
      ``ValueError: Number of degrees of freedom is not zero``。
    """
    conds: Dict[Any, Any] = {v.P: 101325.0, v.N: 1.0}
    first_comp = (
        database.resolve(database.display_elements[0]) if database.display_elements else None
    )
    # 多固定成分（三元及以上必须把所有剩余组分的摩尔分数钉住，否则自由度
    # 不为零）：{"AL": 0.4, "CR": 0.2, ...}；为空时保留旧行为（自动钉第一个
    # 组分 = fixed_x，二元体系够用）
    fixed_map = {
        str(k).upper(): float(vv)
        for k, vv in (fixed_comps or {}).items()
    }
    comp_target = database.resolve(x_target) or x_target

    def _pin_all_except(skip: Optional[str] = None) -> None:
        for el, val in fixed_map.items():
            if skip is not None and el == skip.upper():
                continue
            conds[v.X(database.resolve(el) or el)] = val

    if x_target == "T":
        # 扫温度：组分摩尔分数必须钉死，否则自由度不为零
        conds[v.T] = x_arr
        if fixed_map:
            _pin_all_except()
        elif first_comp:
            conds[v.X(first_comp)] = fixed_x
    elif x_target in ("P", "N"):
        # 扫压强 / 总量：温度与组分都要给定值
        conds[v.T] = fixed_t
        if fixed_map:
            _pin_all_except()
        elif first_comp:
            conds[v.X(first_comp)] = fixed_x
    else:
        # 扫组分：只给这一个组分条件（再多一个就会触发自由度冲突）
        conds[v.T] = fixed_t
        conds[v.X(comp_target)] = x_arr
        _pin_all_except(skip=x_target.upper())
    return conds


def compute_property_curves(
    database: LoadedDatabase,
    comps: Sequence[str],
    phases: Sequence[str],
    target: str,
    x_target: str,
    x_values: Sequence[float],
    options: Optional[Dict[str, Any]] = None,
    figure: Optional[Figure] = None,
    progress: ProgressCB = None,
) -> PropertyResult:
    """计算指定属性随 ``x_target`` 变化的曲线。

    走 pycalphad 的 ``Workspace`` 通道——这是本版本唯一稳定支持"组分扫描"的
    属性入口（ARCHITECTURE T6：``calculate`` 不接受组分条件）。

    Parameters
    ----------
    target
        属性名，如 ``'GM'`` / ``'HM'`` / ``'SM'`` / ``'CPM'``。
    x_target
        扫描轴，通常是组分（如 ``'ZN'``）或 ``'T'``。
    x_values
        扫描采样点。
    options
        ``fixed_t`` 固定温度（默认 600 K）、``fixed_x`` 扫温度时钉死的摩尔分数
        （默认 0.5）、``curve_scope`` 曲线来源（``per_phase`` / ``balance`` /
        ``both``，默认 ``balance`` 以兼容旧行为）、``per_phase_phases`` 逐相计算
        时实际参与求解的相名列表（缺省即 ``phases`` 全部）。后两者都来自属性页。
    """
    options = options or {}
    t0 = time.perf_counter()
    import re

    from pycalphad.core.workspace import Workspace

    # 特殊目标：相分数 / 相中元素含量 / 有序度 / 占位分数。
    # 这些量以"每条曲线一个相"的形式直接从 Workspace 取，不走
    # 逐相单独建模的老路（NP/有序度/占位分数必须在多相平衡里读才有意义）。
    raw_target = str(target).strip()
    up_target = raw_target.upper()
    m_x = re.match(r"^X\(\s*([A-Za-z0-9_#+]+)\s*,\s*([A-Za-z0-9_]+)\s*\)$", raw_target)
    if up_target == "NP":
        special = ("np", "", "")
    elif m_x:
        special = ("xcomp", m_x.group(1).upper(), m_x.group(2).upper())
    elif up_target.startswith("DEGREE_OF_ORDERING("):
        special = ("ordering", raw_target[raw_target.find("(") + 1:raw_target.rfind(")")].strip(), "")
    elif up_target.startswith("SITEFRACTION("):
        special = ("sitefrac", raw_target[raw_target.find("(") + 1:raw_target.rfind(")")].strip(), "")
    else:
        special = None

    resolved_target = (database.resolve(target) or target).upper()
    resolved_x = (x_target or "").strip().upper()
    x_arr = np.asarray(list(x_values), dtype=float)
    fixed_t = float(options.get("fixed_t", 600.0))
    fixed_x = float(options.get("fixed_x", 0.5))

    if resolved_x not in ("T", "P", "N") and not database.resolve(resolved_x):
        raise CalculationError(
            f"扫描轴 {x_target!r} 不在数据库 {database.name} 中",
            f"可选组分：{', '.join(database.display_elements)}",
        )
    if not np.isfinite(x_arr).all() or x_arr.size == 0:
        raise CalculationError("扫描点上存在非法值", "请检查起止值与步长")

    conds = _property_conds(
        database, resolved_x, x_arr, fixed_t, fixed_x,
        fixed_comps=options.get("fixed_comps") or None,
    )
    _pin_comp = (
        database.resolve(database.display_elements[0])
        if database.display_elements
        else resolved_x
    )

    scope = str(options.get("curve_scope", "balance")).strip().lower()
    if scope not in ("per_phase", "balance", "both"):
        scope = "balance"
    want_balance = scope in ("balance", "both")
    want_per_phase = scope in ("per_phase", "both")
    if special is not None:
        # 特殊目标的曲线集来自一次多相平衡的 get_dict / 模型符号枚举，
        # 逐相单独建模没有意义
        scope = "balance"
        want_balance = True
        want_per_phase = False
    # 逐相实际参与求解的相（缺省即全部）。只看勾选框勾中的那几个相，
    # 相多时能省下大量无谓的求解
    _requested = options.get("per_phase_phases") or list(phases)
    per_phase_phases = [p for p in _requested if str(p) in {str(x) for x in phases}] or list(phases)

    try:
        series: Dict[str, Tuple[np.ndarray, np.ndarray]] = {}
        skipped: List[str] = []

        if want_per_phase and resolved_target not in PER_PHASE_KEYS:
            # 化学势 / 活度这类非标准属性无法按相拆分，与其给出一张假图，
            # 不如明确告诉用户"这个属性只能看平衡态"
            want_per_phase = False
            scope = "balance" if not want_balance else "both"

        total_steps = 1 + (len(per_phase_phases) if want_per_phase else 0)
        done = 0

        def _step(msg: str) -> None:
            nonlocal done
            done += 1
            _report(progress, done, max(1, total_steps), msg)

        if scope in ("balance", "both"):
            wks = Workspace(database.dbf, list(comps), list(phases), conds)
            _step(f"正在计算平衡态 {target} …")
            if special is not None:
                mode, phase_s, elem_s = special
                if mode == "np":
                    # 官方文档：wks.get_dict("NP(*)") 一次拿全所有相的摩尔分数
                    for prop, values in wks.get_dict("NP(*)").items():
                        arr = np.atleast_1d(np.asarray(values, dtype=float))
                        if arr.size != x_arr.size:
                            continue
                        keep = np.isfinite(arr) & (arr > 1e-6)
                        if not keep.any():
                            continue
                        series[str(prop)] = (x_arr[keep], arr[keep])
                elif mode == "xcomp":
                    # 官方文档：wks.get(v.X(相, 元素)) = 该相中某元素的含量
                    for j, col in enumerate(_as_curve_columns(wks.get(v.X(phase_s, elem_s)), x_arr.size)):
                        keep = np.isfinite(col)
                        if not keep.any():
                            continue
                        name = f"X({phase_s}, {elem_s})"
                        if j:
                            name += f"#{j + 1}"
                        series[name] = (x_arr[keep], col[keep])
                elif mode == "ordering":
                    from pycalphad import as_property

                    prop = as_property(f"degree_of_ordering({phase_s})")
                    for j, col in enumerate(_as_curve_columns(wks.get(prop), x_arr.size)):
                        keep = np.isfinite(col)
                        if not keep.any():
                            continue
                        name = f"degree_of_ordering({phase_s})"
                        if j:
                            name += f"#{j + 1}"
                        series[name] = (x_arr[keep], col[keep])
                else:  # sitefrac
                    from pycalphad import Model

                    mod = Model(database.dbf, list(comps), phase_s)
                    for sf in mod.site_fractions:
                        try:
                            cols = _as_curve_columns(wks.get(sf), x_arr.size)
                        except Exception:  # noqa: BLE001 - 个别占位符取不到就跳过
                            continue
                        for j, col in enumerate(cols):
                            keep = np.isfinite(col)
                            if not keep.any():
                                continue
                            name = f"{phase_s} {sf}"
                            if j:
                                name += f"#{j + 1}"
                            series[name] = (x_arr[keep], col[keep])
                if not series:
                    raise CalculationError(
                        f"{target} 在扫描范围内没有可用的有限值",
                        "目标相在此区间可能始终不稳定：请调整扫描范围 / 固定条件，"
                        "或换一个目标相",
                    )
            elif resolved_target in PER_PHASE_KEYS:
                # atleast_1d：单点扫描时 pycalphad 返回 0 维数组，取 shape[0] 会越界
                values = np.atleast_1d(np.asarray(wks.get(resolved_target), dtype=float))
                if values.shape[0] != x_arr.size:
                    raise CalculationError(
                        f"属性 {resolved_target} 返回了 {values.shape[0]} 个值，"
                        f"与 {x_arr.size} 个扫描点对不上",
                        "请缩小扫描范围或减少采样点步长",
                    )
                # 过滤非有限值：求解不收敛的点不应把整条线拖"没"
                keep = np.isfinite(values)
                if not keep.any():
                    raise CalculationError(
                        f"属性 {resolved_target} 在扫描范围内没有有限值",
                        "常见原因：固定温度超出数据库有效区间、相选择不当，"
                        "请调整固定温度 / 固定组分或勾选更多相",
                    )
                series["平衡态"] = (x_arr[keep], values[keep])
            else:
                eq = equilibrium(database.dbf, list(comps), list(phases), conds)
                arr = np.asarray(eq.get(resolved_target, []), dtype=float).ravel()
                if arr.size != x_arr.size:
                    raise CalculationError(
                        f"属性 {resolved_target} 返回了 {arr.size} 个值，"
                        f"与 {x_arr.size} 个扫描点对不上",
                        "请缩小扫描范围或减少采样点步长",
                    )
                series["平衡态"] = (x_arr, arr)

        if want_per_phase:
            # T50：逐个相单独建 Workspace（只把该相放进 phases），这样 get()
            # 返回的就是**该相**的摩尔量，长度 = 采样点数。之前只跑一次全相
            # Workspace，get() 给的是"平衡态全局值"（1D），无论传几个相都是
            # 一条线——用户看到的就是"只有平衡相的曲线"。
            for phase_name in per_phase_phases:
                _step(f"正在计算 {phase_name} …")
                try:
                    wks_one = Workspace(
                        database.dbf, list(comps), [str(phase_name)], conds
                    )
                    # atleast_1d：单点扫描时 pycalphad 返回 0 维数组
                    y = np.atleast_1d(
                        np.asarray(wks_one.get(resolved_target), dtype=float)
                    )
                except Exception as exc:  # noqa: BLE001 - 单个相算不出来不该拖垮整批
                    skipped.append(f"{phase_name}（{type(exc).__name__}）")
                    continue
                if y.size != x_arr.size:
                    skipped.append(f"{phase_name}（返回 {y.size} 个值）")
                    continue
                keep = np.isfinite(y)
                if not keep.any():
                    skipped.append(f"{phase_name}（无有限值）")
                    continue
                series[str(phase_name)] = (x_arr[keep], y[keep])

        if not series:
            raise CalculationError(
                f"属性 {resolved_target} 在扫描范围内没有可用的有限值",
                "常见于温度或成分超出了数据库的有效区间，"
                "请调整固定温度 / 固定组分，或在右侧勾选更多相",
            )

        _report(progress, max(1, total_steps), total_steps + 1, "正在绘制属性曲线…")
        if figure is None:
            figure = Figure(figsize=tuple(options.get("figsize", (7, 5))))
        axes = figure.subplots()
        for name, (xs, ys) in series.items():
            if name == "平衡态" and len(series) > 1:
                # both 模式：平衡态当参照线，别和逐相曲线抢视觉重心
                axes.plot(np.asarray(xs), np.asarray(ys), label=name,
                          linestyle="--", color="0.25", linewidth=1.2)
            else:
                axes.plot(np.asarray(xs), np.asarray(ys), label=name)
        axes.set_xlabel(_pretty(resolved_x))
        axes.set_ylabel(f"{target} (J/mol)" if target in ("GM", "HM", "SM", "CPM") else target)
        axes.legend(loc="best", fontsize=8)
        axes.grid(True, alpha=0.3)
        figure.suptitle(f"{target} — {database.name}")
        # T46：plot() 的 autoscale 是"挂起请求"，首次绘制才真正套用。画布挂载时
        # 会先关 autoscale，请求就被作废，viewLim 停在默认 (0,1)——图上"有线却
        # 看不见"。引擎必须在这里把范围落定，交付的图不允许带挂起请求。
        axes.autoscale_view()

        return PropertyResult(
            figure=figure,
            axes=axes,
            series=series,
            property_name=target,
            elapsed_s=time.perf_counter() - t0,
            condition_text=(
                f"扫描 {_pretty(resolved_x)}，"
                + (
                    f"固定 X({_pin_comp}) = {fixed_x:g}"
                    if resolved_x == "T"
                    else f"固定 T = {fixed_t:g} K"
                )
            ),
            x_label=_pretty(resolved_x),
            y_label=target,
            title=f"{target} — {database.name}",
            scope=scope,
            skipped_phases=skipped,
        )

    except CalculationError:
        raise
    except Exception as exc:  # noqa: BLE001
        log_exception(exc, f"计算属性 {target}")
        raise diagnose(exc, f"属性计算 {target}") from exc


# ---------------------------------------------------------------- 工具
def _report(progress: ProgressCB, cur: int, total: int, msg: str) -> None:
    """安全调用进度回调；回调抛错不应中断计算。"""
    if progress is None:
        return
    try:
        progress(cur, total, msg)
    except Exception:  # pragma: no cover
        pass


def default_figure(figsize: Tuple[float, float] = (7.0, 5.0)) -> Figure:
    """创建一个不绑定具体后端的新画布，供引擎在子线程中使用。"""
    return Figure(figsize=figsize)

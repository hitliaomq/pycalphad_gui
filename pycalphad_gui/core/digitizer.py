"""相图图像数字化（纯逻辑层，不碰 Qt）。

把一张**相图位图**（截图 / 扫描件 / 论文插图）还原成可用的数据点，流程是
教科书式的五步，与 UI 上的五个按钮一一对应：

```
1. 选类别   二元（矩形坐标区） / 三元（三角坐标区）
2. 标定     点 3 个已知坐标的点 → 像素 ↔ 数据坐标的仿射变换
3. 去网格   抹掉与坐标轴近似平行且贯通全图的直线（含虚线）
4. 画区域   边界附近点击 → 吸附到最近的边界像素 → 连成多边形 + 打标签
5. 出数据   在多边形内撒网格点，换算成成分 / 温度，追加进表格
```

设计原则：

* **这一层完全不 import PyQt6**——所有几何都是 numpy / matplotlib，
  因此冒烟测试可以合成一张图直接跑完整个流程，不需要起 QApplication；
* 图像一律是 ``uint8`` 的 ``(H, W, 3)`` RGB 数组，Qt 侧负责
  ``QPixmap → ndarray`` / ``ndarray → QPixmap`` 的转换；
* 三元与二元共用**同一套仿射变换**：三点确定一个仿射映射，二元是
  左下 / 右下 / 左上三个角，三元是三角形的三个顶点；差别只在
  "第三个组分 = 1 − x − y" 这一步。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from matplotlib.path import Path as MplPath

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ 常量
DIGITIZE_KINDS: Tuple[str, ...] = ("binary", "ternary")

DIGITIZE_KIND_LABELS: Dict[str, str] = {
    "binary": "二元相图（矩形坐标区）",
    "ternary": "三元相图（三角坐标区）",
}

#: 网格线的候选方向（度）。二元=横竖，三元=三条边方向（两两 60°）
GRID_ANGLES: Dict[str, Tuple[float, ...]] = {
    "binary": (0.0, 90.0),
    "ternary": (0.0, 60.0, 120.0),
}

#: 暗像素阈值（灰度 0~255），低于它算"线条"
DEFAULT_DARK_THRESHOLD = 200
#: 网格线判定：直线长度 / 该方向上的图幅跨度
DEFAULT_SPAN_RATIO = 0.80
#: 三元图单独放宽：三角网格线是**三角形内的弦**，越靠近顶点越短，
#: 用 0.80 的门槛会把大半网格线漏掉（实测 15 条只检出 4 条）
DEFAULT_SPAN_RATIO_TERNARY = 0.35
#: 网格线判定：与坐标轴方向的夹角容差（度）
DEFAULT_ANGLE_TOL = 1.5
#: 网格线判定：线上暗像素数 / 跨度（虚线的占空比可能很低）
DEFAULT_COUNT_RATIO = 0.12
#: 网格线判定：线上**最大间隙** / 跨度（超过它说明不是同一条线，
#: 只是两段墨迹碰巧投到同一条投影带上）。虚线的间隙远小于这个值
DEFAULT_MAX_GAP_RATIO = 0.10
#: 吸附半径（像素）
DEFAULT_SNAP_RADIUS = 14


# ------------------------------------------------------------------ 图像工具
def image_to_array(image: Any) -> np.ndarray:
    """PIL Image / ndarray → ``uint8`` 的 ``(H, W, 3)`` RGB 数组。"""
    arr: np.ndarray
    if hasattr(image, "convert"):  # PIL.Image
        from PIL import Image  # noqa: F401 - 只为类型清晰，实际走 duck typing

        arr = np.asarray(image.convert("RGB"))
    else:
        arr = np.asarray(image)
    if arr.ndim == 2:  # 灰度 → 复制成三通道
        arr = np.repeat(arr[..., None], 3, axis=-1)
    elif arr.shape[-1] == 4:  # RGBA → 丢 alpha
        arr = arr[..., :3]
    elif arr.shape[-1] == 2:  # 灰度 + alpha
        arr = np.repeat(arr[..., :1], 3, axis=-1)
    if arr.dtype != np.uint8:
        arr = np.clip(np.asarray(arr, dtype=float), 0, 255).astype(np.uint8)
    return np.ascontiguousarray(arr)


def to_gray(arr: np.ndarray) -> np.ndarray:
    """RGB → 灰度（``uint8``）。用 Rec.601 权重，与人眼亮度最接近。"""
    rgb = image_to_array(arr).astype(np.float32)
    gray = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    return np.clip(gray, 0, 255).astype(np.uint8)


def dark_mask(gray: np.ndarray, threshold: int = DEFAULT_DARK_THRESHOLD) -> np.ndarray:
    """灰度 → 暗像素布尔掩码（线条为 True）。"""
    return np.asarray(gray, dtype=np.uint8) < int(threshold)


def polygon_mask(shape: Tuple[int, ...], polygon_px: np.ndarray) -> np.ndarray:
    """把多边形（像素坐标）栅格化成布尔掩码，形状取图像前两维。"""
    if polygon_px is None or len(polygon_px) < 3:
        return np.ones(shape[:2], dtype=bool)
    h, w = int(shape[0]), int(shape[1])
    ys, xs = np.mgrid[0:h, 0:w]
    pts = np.column_stack([xs.ravel(), ys.ravel()])
    inside = MplPath(np.asarray(polygon_px, dtype=float)).contains_points(pts)
    return inside.reshape(h, w)


# ------------------------------------------------------------------ 标定
@dataclass
class CalibPoint:
    """一个标定点：图上的像素位置 + 它对应的数据坐标。

    二元的 ``data`` 是 ``(x, y)``（如 X(Cr) 与 T）；三元的 ``data`` 是
    ``(X_A, X_B)``，第三个组分恒为 ``1 - x - y``。
    """

    px: float
    py: float
    data: Tuple[float, float]


class Calibration:
    """三点仿射标定：像素 ↔ 数据坐标。

    三点不共线即确定一个仿射变换。求法用**重心坐标**：任意像素点 P 相对
    三角形（三个标定点）的重心权重 (w₁, w₂, w₃) 就是它在数据空间的重心
    权重，于是 ``data = w₁·d₁ + w₂·d₂ + w₃·d₃``。三元图里权重恰好就是
    三个组分的摩尔分数，一行公式两种图通用。
    """

    def __init__(self, kind: str = "binary",
                 points: Optional[Sequence[CalibPoint]] = None) -> None:
        self.kind = kind if kind in DIGITIZE_KINDS else "binary"
        self.points: List[CalibPoint] = list(points or [])

    # -------------------------------------------------------------- 状态
    @property
    def ready(self) -> bool:
        """三点齐全且不共线。"""
        if len(self.points) != 3:
            return False
        return abs(self._area()) > 1e-6

    def add(self, px: float, py: float, data: Tuple[float, float]) -> None:
        """追加一个标定点（超过 3 个时覆盖最早的，方便反复重标）。"""
        if len(self.points) >= 3:
            self.points.pop(0)
        self.points.append(CalibPoint(float(px), float(py),
                                      (float(data[0]), float(data[1]))))

    def clear(self) -> None:
        self.points.clear()

    # -------------------------------------------------------------- 数学
    def _tri(self) -> np.ndarray:
        return np.array([[p.px, p.py] for p in self.points], dtype=float)

    def _data(self) -> np.ndarray:
        return np.array([p.data for p in self.points], dtype=float)

    def _area(self) -> float:
        tri = self._tri()
        return 0.5 * float(
            (tri[1, 0] - tri[0, 0]) * (tri[2, 1] - tri[0, 1])
            - (tri[2, 0] - tri[0, 0]) * (tri[1, 1] - tri[0, 1])
        )

    def weights(self, px: float, py: float) -> np.ndarray:
        """像素点相对标定三角形的重心权重（三元图里就是三个组分分数）。"""
        if not self.ready:
            raise ValueError("标定未完成：需要三个不共线的标定点")
        tri = self._tri()
        # 用行列式解 2×2 线性方程组，比 np.linalg.solve 对退化情况更直白
        x1, y1 = tri[0]
        x2, y2 = tri[1]
        x3, y3 = tri[2]
        det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
        if abs(det) < 1e-12:
            raise ValueError("标定三角形退化（三点共线）")
        w1 = ((y2 - y3) * (px - x3) + (x3 - x2) * (py - y3)) / det
        w2 = ((y3 - y1) * (px - x3) + (x1 - x3) * (py - y3)) / det
        return np.array([w1, w2, 1.0 - w1 - w2], dtype=float)

    def to_data(self, px: float, py: float) -> Tuple[float, float]:
        """像素 → 数据坐标 ``(x, y)``。"""
        w = self.weights(px, py)
        d = self._data()
        return (float(w[0] * d[0, 0] + w[1] * d[1, 0] + w[2] * d[2, 0]),
                float(w[0] * d[0, 1] + w[1] * d[1, 1] + w[2] * d[2, 1]))

    def to_pixel(self, x: float, y: float) -> Tuple[float, float]:
        """数据坐标 → 像素（画区域回图上时用）。"""
        if not self.ready:
            raise ValueError("标定未完成")
        tri = self._tri()
        d = self._data()
        # 解 d^T · w = (x, y)，且 w1+w2+w3=1
        mat = np.array([
            [d[0, 0], d[1, 0], d[2, 0]],
            [d[0, 1], d[1, 1], d[2, 1]],
            [1.0, 1.0, 1.0],
        ])
        rhs = np.array([x, y, 1.0])
        try:
            w = np.linalg.solve(mat, rhs)
        except np.linalg.LinAlgError:  # pragma: no cover - 标定退化
            raise ValueError("标定退化，无法反算像素坐标") from None
        return (float(w @ tri[:, 0]), float(w @ tri[:, 1]))

    def composition(self, px: float, py: float) -> Tuple[float, float, float]:
        """三元图的三个组分分数（二元图返回 ``(x, 1-x, nan)``）。"""
        if self.kind == "ternary":
            w = self.weights(px, py)
            return (float(w[0]), float(w[1]), float(w[2]))
        x, _y = self.to_data(px, py)
        return (float(x), float(1.0 - x), float("nan"))

    # -------------------------------------------------------------- 坐标区
    def region_polygon(self) -> Optional[np.ndarray]:
        """坐标区轮廓（像素）：二元是矩形四角，三元是三角形三顶点。"""
        if not self.ready:
            return None
        tri = self._tri()
        if self.kind == "ternary":
            return tri.copy()
        # 二元：p1 原点，p2 沿 x 轴，p3 沿 y 轴 → 第四角是 p2 + p3 - p1
        p1, p2, p3 = tri
        p4 = p2 + p3 - p1
        return np.array([p1, p2, p4, p3], dtype=float)


# ------------------------------------------------------------------ 网格线
def _line_span(shape: Tuple[int, ...], angle_deg: float) -> float:
    """某个方向上图像的最大跨度（像素），用于判定"贯通全图"。"""
    h, w = float(shape[0]), float(shape[1])
    rad = np.deg2rad(angle_deg)
    return abs(w * np.cos(rad)) + abs(h * np.sin(rad))


def _extent_along(mask: np.ndarray, ux: float, uy: float) -> float:
    """布尔区域沿方向 ``(ux, uy)`` 的实际跨度（像素）。

    判定"贯通坐标区"必须拿**坐标区自己的跨度**当分母，而不是整幅图的
    跨度：一张 600×400 的图里，绘图框往往只占中间 320 px 高，用 400 当
    分母会让正好贯通的竖网格线算出 0.79 的比值而被误杀（实测漏检）。
    """
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return 0.0
    t = xs * ux + ys * uy
    return float(t.max() - t.min())


def detect_grid_lines(
    gray: np.ndarray,
    kind: str = "binary",
    threshold: int = DEFAULT_DARK_THRESHOLD,
    angle_tol: float = DEFAULT_ANGLE_TOL,
    span_ratio: Optional[float] = None,
    count_ratio: float = DEFAULT_COUNT_RATIO,
    max_gap_ratio: float = DEFAULT_MAX_GAP_RATIO,
    region: Optional[np.ndarray] = None,
) -> List[Dict[str, float]]:
    """找出"与坐标轴近似平行且贯通整个坐标区"的直线（含虚线）。

    做法不是 Hough 变换，而是**按方向做投影累加**（Radon 的简化版），
    这更贴合这里的判定条件：

    * 沿方向 θ 把暗像素投影到与之垂直的坐标 ``s`` 上，按 1 px 分箱；
    * 同一条网格线的暗像素必然落在同一个（或相邻几个）``s`` 箱里，
      **虚线也一样**，因此天然免疫虚线；
    * 再看这个箱里暗像素沿 θ 的**最长缺口**：缺口占比不超过跨度的
      ``max_gap_ratio`` 就判定为贯通线（用缺口而不是"最长连续段"，
      虚线才不会因为 16 亮 / 24 暗的节奏被整条否掉，见 T63）。

    返回每条线的信息：方向、投影偏移、起止位置、暗像素数。
    """
    if span_ratio is None:
        span_ratio = (DEFAULT_SPAN_RATIO_TERNARY if kind == "ternary"
                      else DEFAULT_SPAN_RATIO)
    # 入口统一归一化：允许直接传 RGB 图，省得每个调用点都手写 to_gray
    mask = dark_mask(to_gray(gray), threshold)
    if region is not None:
        region = np.asarray(region, dtype=bool)
        mask = mask & region
    h, w = mask.shape[:2]
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return []

    found: List[Dict[str, float]] = []
    # 跨度分母优先取**坐标区**（标定后传入）；没标定就退而用"墨迹自身的
    # 跨度"——绘图框外的空白页不该算进分母，否则贯通的网格线比值偏低。
    span_source = region if region is not None else mask
    for angle in GRID_ANGLES.get(kind, GRID_ANGLES["binary"]):
        # 允许 ±angle_tol 的偏差：把邻近角度的投影也并进来，
        # 否则"差 1° 的网格线"会散落到相邻 s 箱里被判成两条短线。
        for offset_deg in (0.0, -angle_tol, angle_tol):
            rad = np.deg2rad(angle + offset_deg)
            ux, uy = np.cos(rad), np.sin(rad)
            nx, ny = -np.sin(rad), np.cos(rad)
            s_all = xs * nx + ys * ny          # 垂直方向：分箱依据
            t_all = xs * ux + ys * uy          # 平行方向：判长度
            s_min = float(s_all.min())
            bins = np.floor(s_all - s_min).astype(np.int64)
            counts = np.bincount(bins)
            span = _extent_along(span_source, ux, uy) or _line_span((h, w), angle)
            if span <= 0:
                continue
            # 只考察"像条线"的峰箱，且统计时**连带相邻 ±1 箱**：
            # 斜线（60°/120°）栅格化后是阶梯状，像素会横跨 2~3 个投影箱，
            # 只看单箱会把一条完整的斜网格线切碎成好几段短线（实测漏检）。
            peak_floor = max(3, int(0.15 * counts.max()))
            for bindex in np.nonzero(counts >= peak_floor)[0]:
                sel = np.abs(bins - bindex) <= 1
                t_vals = np.sort(t_all[sel])
                if t_vals.size < 3:
                    continue
                length = float(t_vals[-1] - t_vals[0])
                if length < span_ratio * span:
                    continue
                # 虚线判据：看**最大间隙**而不是最长连续段。
                # 虚线的间隙是规整的小间隙（十几到几十像素），而"两段无关
                # 的墨迹碰巧落在同一投影箱"的间隙则是图幅级别。取最长连续
                # 段会把虚线整条判死（实测 16 px 实 + 24 px 空全部漏检）。
                if t_vals.size > 1:
                    max_gap = float(np.diff(t_vals).max())
                    if max_gap > max_gap_ratio * span:
                        continue
                if t_vals.size < count_ratio * span:
                    continue
                s0 = s_min + float(bindex) + 0.5
                found.append({
                    "angle": float(angle),
                    # 实际用于投影的角度（含 ±tol 修正）。擦除时必须用它：
                    # 线可能偏 1.5°，350 px 长的线上这就是 9 px 的偏移，
                    # 按理论角度擦会整条擦空（三元实测残留 2000+ 像素）。
                    "angle_used": float(angle + offset_deg),
                    "offset": s0,
                    "t_min": float(t_vals[0]),
                    "t_max": float(t_vals[-1]),
                    "count": int(t_vals.size),
                    "span": float(span),
                })
    return _dedup_lines(found)


def _dedup_lines(lines: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """同一条线在 ±tol 两个角度里会被各检一次，按 (角度, 偏移) 去重。"""
    out: List[Dict[str, float]] = []
    for line in sorted(lines, key=lambda d: (-d["count"], d["offset"])):
        for kept in out:
            if abs(kept["angle"] - line["angle"]) < 1e-6 and \
                    abs(kept["offset"] - line["offset"]) < 2.5:
                break
        else:
            out.append(line)
    return out


def remove_grid_lines(
    image: Any,
    kind: str = "binary",
    threshold: int = DEFAULT_DARK_THRESHOLD,
    region: Optional[np.ndarray] = None,
    fill: int = 255,
    **kwargs: Any,
) -> Tuple[np.ndarray, List[Dict[str, float]]]:
    """抹掉网格线，返回 ``(清理后的图像, 被抹掉的线列表)``。

    只在**检测到的线段范围内**（``t_min``~``t_max``）涂白，不做整条带
    的擦除——否则坐标轴外的刻度数字会被顺手抹掉。
    """
    arr = image_to_array(image).copy()
    h, w = arr.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w]
    all_lines: List[Dict[str, float]] = []
    # 多轮擦除：一次擦完常有 5% 左右的残留（相邻投影箱的副本偏移了 1 px），
    # 残留像素会干扰后面的边界吸附，所以擦到干净为止（最多 3 轮）。
    for _ in range(3):
        lines = detect_grid_lines(to_gray(arr), kind=kind,
                                  threshold=threshold, region=region, **kwargs)
        if not lines:
            break
        ink = dark_mask(to_gray(arr), threshold)
        if region is not None:
            ink = ink & np.asarray(region, dtype=bool)
        for line in lines:
            rad = np.deg2rad(line.get("angle_used", line["angle"]))
            ux, uy = np.cos(rad), np.sin(rad)
            nx, ny = -np.sin(rad), np.cos(rad)
            s = xs * nx + ys * ny
            t = xs * ux + ys * uy
            # ① 几何条纹：沿检测到的角度与延伸范围整条涂白——虚线的空档
            #    靠它补上（只按墨迹膨胀是连不起 20 px 以上的空档的）。
            stripe = (np.abs(s - line["offset"]) <= 2.0) & \
                     (t >= line["t_min"] - 2.0) & (t <= line["t_max"] + 2.0)
            # ② 墨迹膨胀：角度哪怕只差 1.5°，300 px 长的线上就是 8 px 偏移，
            #    ① 会擦空。所以再对"这条线上确实有墨的位置"膨胀几像素后
            #    一并擦掉，把①的偏差补回来（三元实测残留 5% → 0.7%）。
            on_line = ink & (np.abs(s - line["offset"]) <= 3.0) & \
                      (t >= line["t_min"] - 3.0) & (t <= line["t_max"] + 3.0)
            if on_line.any():
                from scipy.ndimage import binary_dilation

                # 只膨胀 3×3：再大就会吃掉与网格线相交的真实相界
                # （实测 5×5 会把斜相界啃掉约 20%）
                stripe = stripe | binary_dilation(
                    on_line, structure=np.ones((3, 3), dtype=bool)
                )
            arr[stripe] = (fill, fill, fill)
        all_lines.extend(lines)
    return arr, all_lines


# ------------------------------------------------------------------ 边界吸附
def snap_to_boundary(
    gray: np.ndarray,
    px: float,
    py: float,
    radius: int = DEFAULT_SNAP_RADIUS,
    threshold: int = DEFAULT_DARK_THRESHOLD,
) -> Optional[Tuple[float, float]]:
    """把用户的点击吸附到最近的边界（暗）像素。

    点击位置离真实线条总有偏差（手抖 / 缩放），所以取搜索窗内**欧氏距离
    最近的暗像素**；再用它周围 1 px 的暗像素做质心，得到亚像素精度。
    窗内一个暗像素都没有就返回 ``None``（UI 提示"附近没找到边界"）。
    """
    mask = dark_mask(to_gray(gray), threshold)
    h, w = mask.shape[:2]
    r = int(max(1, radius))
    x0, x1 = max(0, int(px) - r), min(w, int(px) + r + 1)
    y0, y1 = max(0, int(py) - r), min(h, int(py) + r + 1)
    if x1 <= x0 or y1 <= y0:
        return None
    sub = mask[y0:y1, x0:x1]
    ys, xs = np.nonzero(sub)
    if xs.size == 0:
        return None
    dx = xs + x0 - px
    dy = ys + y0 - py
    dist = dx * dx + dy * dy
    best = int(np.argmin(dist))
    bx, by = int(xs[best]) + x0, int(ys[best]) + y0
    # 亚像素：以命中点为中心取 3×3 暗像素质心
    cy0, cy1 = max(0, by - 1), min(h, by + 2)
    cx0, cx1 = max(0, bx - 1), min(w, bx + 2)
    near_y, near_x = np.nonzero(mask[cy0:cy1, cx0:cx1])
    if near_x.size:
        bx = float(near_x.mean()) + cx0
        by = float(near_y.mean()) + cy0
    return (float(bx), float(by))


def project_to_polygon(
    polygon_px: np.ndarray, px: float, py: float, tol: float = 8.0
) -> Optional[Tuple[float, float]]:
    """把点投影到多边形最近的边上（距离超过 ``tol`` 返回 ``None``）。

    用途：坐标轴边框常被第 3 步当成"贯通全图的网格线"抹掉了，而**框线恰恰
    是贴边相区的合法边界**。这时点击附近找不到墨迹，就退回到"投影到标定
    出的坐标区轮廓"，用户照样能把贴边的单相区圈出来。
    """
    poly = np.asarray(polygon_px, dtype=float)
    if poly.ndim != 2 or poly.shape[0] < 2:
        return None
    best: Optional[Tuple[float, float]] = None
    best_dist = float("inf")
    n = poly.shape[0]
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        seg_len2 = dx * dx + dy * dy
        t = 0.0 if seg_len2 <= 0 else \
            ((px - ax) * dx + (py - ay) * dy) / seg_len2
        t = min(max(t, 0.0), 1.0)
        qx, qy = ax + t * dx, ay + t * dy
        dist = float(np.hypot(qx - px, qy - py))
        if dist < best_dist:
            best_dist = dist
            best = (float(qx), float(qy))
    if best is None or best_dist > float(tol):
        return None
    return best


# ------------------------------------------------------------------ 区域与取样
@dataclass
class DigitizedRegion:
    """一个标定好的相区：像素边界点 + 标签 + 取样后的数据点。"""

    region_id: int
    label: str = ""
    points_px: List[Tuple[float, float]] = field(default_factory=list)

    def points_data(self, calib: Calibration) -> np.ndarray:
        """边界点的**数据坐标**数组 ``(n, 2)``。"""
        return np.array([calib.to_data(px, py) for px, py in self.points_px],
                        dtype=float)

    @property
    def closed(self) -> bool:
        """三点及以上才能围成区域。"""
        return len(self.points_px) >= 3


def sample_grid(
    polygon_data: np.ndarray,
    kind: str = "binary",
    step_x: float = 0.02,
    step_y: float = 25.0,
    limits: Optional[Tuple[float, float, float, float]] = None,
) -> np.ndarray:
    """在多边形内部撒规则网格点，返回数据坐标数组 ``(n, 2)``。

    * 二元：在包围盒里按 ``step_x`` / ``step_y`` 撒点；
    * 三元：只撒落在成分三角形内（``x + y ≤ 1``）的点，避免白算一半。
    """
    poly = np.asarray(polygon_data, dtype=float)
    if poly.ndim != 2 or poly.shape[0] < 3:
        return np.empty((0, 2), dtype=float)
    path = MplPath(poly)

    if kind == "ternary":
        xs = np.arange(0.0, 1.0 + 1e-9, max(step_x, 1e-6))
        ys = np.arange(0.0, 1.0 + 1e-9, max(step_x, 1e-6))
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        pts = np.column_stack([gx.ravel(), gy.ravel()])
        pts = pts[(pts[:, 0] + pts[:, 1]) <= 1.0 + 1e-9]
    else:
        if limits is not None:
            x0, x1, y0, y1 = limits
        else:
            x0, x1 = float(poly[:, 0].min()), float(poly[:, 0].max())
            y0, y1 = float(poly[:, 1].min()), float(poly[:, 1].max())
        xs = np.arange(x0, x1 + 1e-12, max(step_x, 1e-9))
        ys = np.arange(y0, y1 + 1e-12, max(step_y, 1e-9))
        gx, gy = np.meshgrid(xs, ys, indexing="ij")
        pts = np.column_stack([gx.ravel(), gy.ravel()])
    if pts.size == 0:
        return np.empty((0, 2), dtype=float)
    inside = path.contains_points(pts)
    return pts[inside]


def regions_to_frame(
    regions: Sequence[DigitizedRegion],
    calib: Calibration,
    axis_x: str = "X",
    axis_y: str = "T",
    comp_names: Optional[Sequence[str]] = None,
    step_x: float = 0.02,
    step_y: float = 25.0,
) -> pd.DataFrame:
    """把若干区域取样成一张长表；区域按标定顺序**上下拼接**。

    二元列：``区域 / 相标签 / X(轴名) / 1-X / 轴名``；
    三元列：``区域 / 相标签 / X(A) / X(B) / X(C)``（C = 1 − A − B）。
    后续区域的点直接追加在前一个区域的点**下面**，符合手工数字化的习惯。
    """
    rows: List[Dict[str, Any]] = []
    names = list(comp_names or ("A", "B", "C"))
    for region in regions:
        poly = region.points_data(calib) if region.closed else np.empty((0, 2))
        pts = sample_grid(poly, kind=calib.kind, step_x=step_x, step_y=step_y) \
            if poly.size else np.empty((0, 2))
        for x, y in pts:
            if calib.kind == "ternary":
                row = {
                    "区域": region.region_id,
                    "相标签": region.label,
                    f"X({names[0]})": round(float(x), 6),
                    f"X({names[1]})": round(float(y), 6),
                    f"X({names[2]})": round(float(1.0 - x - y), 6),
                }
            else:
                row = {
                    "区域": region.region_id,
                    "相标签": region.label,
                    f"X({axis_x})": round(float(x), 6),
                    f"X(1-{axis_x})": round(float(1.0 - x), 6),
                    str(axis_y): round(float(y), 4),
                }
            rows.append(row)
    return pd.DataFrame(rows)


def save_digitized_csv(frame: pd.DataFrame, path: Any) -> None:
    """导出数字化结果（UTF-8 BOM，Excel 直接双击不乱码）。"""
    frame.to_csv(str(path), index=False, encoding="utf-8-sig")


__all__ = [
    "DIGITIZE_KINDS", "DIGITIZE_KIND_LABELS", "GRID_ANGLES",
    "CalibPoint", "Calibration", "DigitizedRegion",
    "image_to_array", "to_gray", "dark_mask", "polygon_mask",
    "detect_grid_lines", "remove_grid_lines", "snap_to_boundary",
    "sample_grid", "regions_to_frame", "save_digitized_csv",
]

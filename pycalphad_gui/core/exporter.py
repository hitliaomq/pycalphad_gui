"""结果导出。

两类产物：
1. **图像** —— PNG / SVG / PDF / JPG，直接从 ``matplotlib`` 的 Figure 写出；
2. **数据** —— CSV / XLSX，供后续拟合或报表。

导出前会校验输出路径的父目录存在，避免写到不存在的目录后再报无意义的错误。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import numpy as np
from matplotlib.figure import Figure

from .diagnostics import CalculationError
from ..config import EXPORT_DATA_FORMATS, EXPORT_IMAGE_FORMATS

logger = logging.getLogger(__name__)

#: matplotlib 支持的后缀与格式的对应关系
_SUFFIX_MAP = {
    "png": "png",
    "jpg": "jpg",
    "jpeg": "jpg",
    "svg": "svg",
    "pdf": "pdf",
}


def _prepare_output(path: Path) -> Path:
    """校验并归一化输出路径，父目录不存在时自动创建。"""
    if path.parent and not path.parent.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CalculationError(
                f"无法创建输出目录：{path.parent}",
                str(exc),
            ) from exc
    return path


def export_figure(figure: Figure, path: str | Path, dpi: int = 200, *, bbox_inches: str = "tight") -> Path:
    """把 Figure 导出为图像文件。

    Parameters
    ----------
    figure
        待导出的画布。
    path
        目标文件；扩展名决定格式（png / svg / pdf / jpg）。
    dpi
        位图分辨率。
    bbox_inches
        传 ``'tight'`` 可裁掉多余白边；导出 PDF 时也可用于节省体积。

    Raises
    ------
    CalculationError
        扩展名不支持或写入失败。
    """
    path = _prepare_output(Path(path))
    suffix = path.suffix.lower().lstrip(".")
    fmt = _SUFFIX_MAP.get(suffix)
    if fmt is None:
        raise CalculationError(
            f"不支持的图像格式：.{suffix}",
            f"可用格式：{', '.join(sorted(set(EXPORT_IMAGE_FORMATS)))}",
        )
    try:
        figure.savefig(path, dpi=dpi, format=fmt, bbox_inches=bbox_inches)
    except Exception as exc:  # noqa: BLE001
        raise CalculationError(f"图像写入失败：{path.name}", str(exc)) from exc
    logger.info("已导出图像 %s (%.1f KB)", path, path.stat().st_size / 1024)
    return path


def export_series_csv(
    series: Sequence[Tuple[str, np.ndarray, np.ndarray]],
    path: str | Path,
    x_label: str = "x",
    y_label: str = "y",
) -> Path:
    """把一条或多条属性曲线导出为 CSV。

    Parameters
    ----------
    series
        ``[(名称, x数组, y数组), ...]``。
    """
    series = list(series)
    if not series:
        raise CalculationError("没有可导出的曲线数据")

    path = _prepare_output(Path(path))
    width = max(len(np.asarray(x)) for _, x, _ in series)
    header = [x_label] + [f"{name}" for name, _, _ in series]
    lines: List[str] = [",".join(header)]

    for i in range(width):
        cells: List[str] = []
        for _, x, y in series:
            xs, ys = np.asarray(x), np.asarray(y)
            cells.append(f"{xs[i]:.10g}" if i < xs.size else "")
            cells.append(f"{ys[i]:.10g}" if i < ys.size else "")
        # 每组曲线占两列（x, y）
        rebuilt: List[str] = []
        for idx in range(0, len(cells), 2):
            rebuilt.extend([cells[idx], cells[idx + 1]])
        lines.append(",".join(rebuilt))

    try:
        path.write_text("\n".join(lines), encoding="utf-8-sig")
    except OSError as exc:
        raise CalculationError(f"CSV 写入失败：{path.name}", str(exc)) from exc
    logger.info("已导出曲线数据 %s", path)
    return path


def export_dataframe(df, path: str | Path, sheet_name: str = "高通量结果") -> Path:
    """导出高通量结果为 CSV 或 XLSX。

    XLSX 需要 ``openpyxl``；缺失时给出可执行的安装提示而非原始 ImportError。
    """
    path = _prepare_output(Path(path))
    suffix = path.suffix.lower().lstrip(".")

    if suffix == "csv":
        try:
            df.to_csv(path, index=False, encoding="utf-8-sig")
        except OSError as exc:
            raise CalculationError(f"CSV 写入失败：{path.name}", str(exc)) from exc
    elif suffix in ("xlsx", "xls"):
        try:
            df.to_excel(path, index=False, sheet_name=sheet_name)
        except ModuleNotFoundError as exc:
            raise CalculationError(
                "缺少 openpyxl，无法写出 Excel 文件",
                "可执行：pip install openpyxl；或改用 .csv 导出",
            ) from exc
        except OSError as exc:
            raise CalculationError(f"Excel 写入失败：{path.name}", str(exc)) from exc
    else:
        raise CalculationError(
            f"不支持的数据格式：.{suffix}", f"可用格式：{', '.join(EXPORT_DATA_FORMATS)}"
        )
    logger.info("已导出数据 %s", path)
    return path


def suggest_export_name(prefix: str, fmt: str) -> str:
    """生成默认导出文件名。"""
    cleaned = prefix.strip().replace(" ", "_") or "plot"
    return f"{cleaned}.{fmt}"

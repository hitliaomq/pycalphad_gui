"""「数字化相图」选项卡 —— 把一张相图位图还原成数据表。

照着手工数字化的习惯排了五步，**每一步对应一组控件**，从上往下做即可：

```
1. 选类别   二元 / 三元（决定光标形状与坐标换算方式）
2. 标定     按下「开始标定」→ 图上依次点 3 个已知坐标的点
3. 去网格   抹掉与坐标轴平行且贯通全图的直线（含虚线），可反复调阈值
4. 画区域   边界附近点一下 → 自动吸附到最近的边界像素 → 连成区域打标签
5. 出数据   区域内撒网格点，换算成成分/温度，追加到表格（可导 CSV）
```

与画布的协作：本选项卡**不自己画图**，所有交互都通过
:class:`DigitizeCanvas` 完成（主窗口把画布 ``attach_canvas`` 进来）。
右键点画布 = 删掉最近的那个点，这是第 4 步最常用的纠错操作。

Qt 侧的一个硬约束：PyQt6 对槽函数里逃逸的异常是**直接 abort 进程**
（不是打日志），所以每个入口都用 ``try/except`` 包住并转成状态栏提示。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.digitizer import (
    DEFAULT_DARK_THRESHOLD,
    DIGITIZE_KIND_LABELS,
    DIGITIZE_KINDS,
    Calibration,
    DigitizedRegion,
    polygon_mask,
    project_to_polygon,
    regions_to_frame,
    remove_grid_lines,
    save_digitized_csv,
    snap_to_boundary,
)
from .digitize_canvas import DigitizeCanvas
from .. import i18n

logger = logging.getLogger(__name__)

#: 标定点的提示语（按 类别 → 第几个点）
_CALIB_HINT = {
    "binary": ("① 点击坐标区**左下角**（x 最小、y 最小）",
               "② 点击坐标区**右下角**（x 最大、y 最小）",
               "③ 点击坐标区**左上角**（x 最小、y 最大）"),
    "ternary": ("① 点击三角形**左下顶点**（组分 A = 1）",
                "② 点击三角形**右下顶点**（组分 B = 1）",
                "③ 点击三角形**上顶点**（组分 C = 1）"),
}


class DigitizeTab(QWidget):
    """数字化相图。"""

    #: 状态栏文本
    status = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._canvas: Optional[DigitizeCanvas] = None
        self._original: Optional[np.ndarray] = None   # 导入的原图
        self._working: Optional[np.ndarray] = None    # 去网格线后的工作图
        self._calib = Calibration("binary")
        self._mode = "idle"          # idle / calib / boundary
        self._regions: List[DigitizedRegion] = []
        self._current_points: List[Tuple[float, float]] = []
        self._frame: Optional[pd.DataFrame] = None
        self._next_region_id = 1
        self._build_ui()

    # ---------------------------------------------------------------- 界面
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # ---------------- 1. 类别 ----------------
        box1 = QGroupBox("1. 相图类别", self)
        form1 = QVBoxLayout(box1)
        row_kind = QHBoxLayout()
        self._kind = QComboBox(self)
        for key in DIGITIZE_KINDS:
            self._kind.addItem(DIGITIZE_KIND_LABELS[key], key)
        self._kind.currentIndexChanged.connect(self._on_kind_changed)
        row_kind.addWidget(QLabel("类别"), 0)
        row_kind.addWidget(self._kind, 1)
        form1.addLayout(row_kind)

        # 二元：X / Y 轴名与量程；三元：三个组分名
        self._binary_row = QWidget(self)
        br = QHBoxLayout(self._binary_row)
        br.setContentsMargins(0, 0, 0, 0)
        self._axis_x = QLineEdit("Cr", self)
        self._axis_x.setToolTip("横轴（组分）名称，会作为表格列名 X(名称)")
        self._axis_y = QLineEdit("T (K)", self)
        self._axis_y.setToolTip("纵轴名称（一般是温度），会作为表格列名")
        br.addWidget(QLabel("X 轴"), 0)
        br.addWidget(self._axis_x, 1)
        br.addWidget(QLabel("Y 轴"), 0)
        br.addWidget(self._axis_y, 1)
        form1.addWidget(self._binary_row)

        self._ternary_row = QWidget(self)
        tr = QHBoxLayout(self._ternary_row)
        tr.setContentsMargins(0, 0, 0, 0)
        self._comp = [QLineEdit(n, self) for n in ("A", "B", "C")]
        for i, edit in enumerate(self._comp):
            tr.addWidget(QLabel(f"组分{i + 1}"), 0)
            tr.addWidget(edit, 1)
        form1.addWidget(self._ternary_row)

        self._range_row = QWidget(self)
        rr = QHBoxLayout(self._range_row)
        rr.setContentsMargins(0, 0, 0, 0)
        self._x_min, self._x_max = self._spin(0.0, 1.0, 0.0), self._spin(0.0, 1.0, 1.0)
        self._y_min = self._spin(0.0, 6000.0, 300.0, step=50.0, decimals=1)
        self._y_max = self._spin(0.0, 6000.0, 1500.0, step=50.0, decimals=1)
        rr.addWidget(QLabel("X 范围"), 0)
        rr.addWidget(self._x_min)
        rr.addWidget(QLabel("~"), 0)
        rr.addWidget(self._x_max)
        rr.addWidget(QLabel("Y 范围"), 0)
        rr.addWidget(self._y_min)
        rr.addWidget(QLabel("~"), 0)
        rr.addWidget(self._y_max)
        form1.addWidget(self._range_row)
        layout.addWidget(box1)

        # ---------------- 2. 标定 ----------------
        box2 = QGroupBox("2. 标定区域", self)
        form2 = QVBoxLayout(box2)
        self._hint = QLabel("点击「开始标定」，然后按提示在图上点三个点", self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color:#7a8494;")
        form2.addWidget(self._hint)
        row2 = QHBoxLayout()
        self._btn_calib = QPushButton("开始标定", self)
        self._btn_calib.clicked.connect(lambda _c: self._toggle_calib())
        self._btn_recall = QPushButton("重新标定", self)
        self._btn_recall.clicked.connect(lambda _c: self._reset_calib())
        row2.addWidget(self._btn_calib)
        row2.addWidget(self._btn_recall)
        row2.addStretch(1)
        form2.addLayout(row2)
        layout.addWidget(box2)

        # ---------------- 3. 去网格线 ----------------
        box3 = QGroupBox("3. 去除网格线", self)
        form3 = QVBoxLayout(box3)
        row3 = QHBoxLayout()
        self._threshold = self._spin(0.0, 255.0, float(DEFAULT_DARK_THRESHOLD),
                                     step=5.0, decimals=0)
        self._threshold.setToolTip("灰度低于此值算作线条；线太浅就调高，杂点太多就调低")
        self._btn_grid = QPushButton("去除网格线", self)
        self._btn_grid.clicked.connect(lambda _c: self._remove_grid())
        self._btn_restore = QPushButton("恢复原图", self)
        self._btn_restore.clicked.connect(lambda _c: self._restore_image())
        row3.addWidget(QLabel("阈值"), 0)
        row3.addWidget(self._threshold)
        row3.addWidget(self._btn_grid)
        row3.addWidget(self._btn_restore)
        row3.addStretch(1)
        form3.addLayout(row3)
        self._grid_info = QLabel("未处理", self)
        self._grid_info.setWordWrap(True)
        self._grid_info.setStyleSheet("color:#7a8494;")
        form3.addWidget(self._grid_info)
        layout.addWidget(box3)

        # ---------------- 4. 区域边界 ----------------
        box4 = QGroupBox("4. 标定相区域边界", self)
        form4 = QVBoxLayout(box4)
        row4 = QHBoxLayout()
        self._btn_region = QPushButton("开始新区域", self)
        self._btn_region.clicked.connect(lambda _c: self._start_region())
        self._btn_finish = QPushButton("完成区域（设标签）", self)
        self._btn_finish.clicked.connect(lambda _c: self._finish_region())
        self._btn_undo = QPushButton("删最后一点", self)
        self._btn_undo.clicked.connect(lambda _c: self._undo_point())
        self._btn_clear_pts = QPushButton("清空本区域", self)
        self._btn_clear_pts.clicked.connect(lambda _c: self._clear_points())
        for btn in (self._btn_region, self._btn_finish, self._btn_undo,
                    self._btn_clear_pts):
            row4.addWidget(btn)
        row4.addStretch(1)
        form4.addLayout(row4)
        self._pt_info = QLabel("边界点：0 个（右键点图删除最近的点）", self)
        self._pt_info.setWordWrap(True)
        self._pt_info.setStyleSheet("color:#7a8494;")
        form4.addWidget(self._pt_info)
        layout.addWidget(box4)

        # ---------------- 5. 生成数据 ----------------
        box5 = QGroupBox("5. 生成数据", self)
        form5 = QVBoxLayout(box5)
        row5 = QHBoxLayout()
        self._step_x = self._spin(0.005, 0.2, 0.02, step=0.005, decimals=3)
        self._step_y = self._spin(1.0, 200.0, 25.0, step=5.0, decimals=1)
        self._btn_generate = QPushButton("生成数据", self)
        self._btn_generate.clicked.connect(lambda _c: self._generate())
        self._btn_export = QPushButton("导出 CSV", self)
        self._btn_export.clicked.connect(lambda _c: self._export_csv())
        row5.addWidget(QLabel("成分步长"), 0)
        row5.addWidget(self._step_x)
        self._step_y_label = QLabel("纵轴步长", self)
        row5.addWidget(self._step_y_label, 0)
        row5.addWidget(self._step_y)
        row5.addWidget(self._btn_generate)
        row5.addWidget(self._btn_export)
        row5.addStretch(1)
        form5.addLayout(row5)

        self._table = QTableWidget(self)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setMinimumHeight(160)
        form5.addWidget(self._table, 1)
        self._data_info = QLabel("尚未生成数据", self)
        self._data_info.setWordWrap(True)
        self._data_info.setStyleSheet("color:#7a8494;")
        form5.addWidget(self._data_info)
        layout.addWidget(box5, 1)

        self._on_kind_changed(0)

    def _spin(self, minimum: float, maximum: float, value: float,
              step: float = 0.01, decimals: int = 4) -> QDoubleSpinBox:
        box = QDoubleSpinBox(self)
        box.setDecimals(decimals)
        box.setRange(minimum, maximum)
        box.setSingleStep(step)
        box.setValue(value)
        return box

    # ---------------------------------------------------------------- 接线
    def attach_canvas(self, canvas: DigitizeCanvas) -> None:
        """接上主窗口里的图像画布（画布由主窗口持有，这里只连线）。"""
        self._canvas = canvas
        canvas.clicked.connect(self._on_canvas_clicked)
        canvas.right_clicked.connect(self._on_canvas_right_clicked)

    def set_image(self, image: object) -> None:
        """导入新图：清空全部中间状态，重新开局。"""
        from ..core.digitizer import image_to_array

        arr = image_to_array(image)
        self._original = arr
        self._working = arr.copy()
        self._reset_calib(quiet=True)
        self._regions.clear()
        self._current_points.clear()
        self._frame = None
        self._next_region_id = 1
        self._table.setRowCount(0)
        self._table.setColumnCount(0)
        self._data_info.setText(i18n.tr("尚未生成数据"))
        self._grid_info.setText(i18n.tr("未处理"))
        if self._canvas is not None:
            self._canvas.set_image(arr)
            self._canvas.set_regions([])
            self._canvas.set_calib_points([])
            self._canvas.set_boundary_points([])
        self.status.emit(f"已导入图像 {arr.shape[1]}×{arr.shape[0]}，请从第 1 步开始")

    def configure(self, database, elements: Sequence[str], phases) -> None:
        """主窗口联动：用当前勾选的元素预填组分名 / 轴名。"""
        try:
            names = [e for e in (elements or [])][:3]
            if len(names) >= 3:
                self._kind.setCurrentIndex(DIGITIZE_KINDS.index("ternary"))
                for edit, name in zip(self._comp, names):
                    edit.setText(str(name).title())
            elif len(names) == 2:
                self._kind.setCurrentIndex(DIGITIZE_KINDS.index("binary"))
                self._axis_x.setText(str(names[-1]).title())
        except Exception as exc:  # noqa: BLE001 - 槽里不能让异常逃逸
            logger.debug("数字化页联动失败：%s", exc)

    # ---------------------------------------------------------------- 步骤 1
    @property
    def kind(self) -> str:
        return str(self._kind.currentData() or "binary")

    def _on_kind_changed(self, _index: int) -> None:
        is_binary = self.kind == "binary"
        self._binary_row.setVisible(is_binary)
        self._range_row.setVisible(is_binary)
        self._ternary_row.setVisible(not is_binary)
        self._step_y.setVisible(is_binary)
        self._step_y_label.setVisible(is_binary)
        self._calib.kind = self.kind
        if self._canvas is not None and self._mode != "idle":
            self._canvas.set_cursor_mode("cross" if is_binary else "tri")

    # ---------------------------------------------------------------- 步骤 2
    def _toggle_calib(self) -> None:
        if self._mode == "calib":
            self._set_mode("idle")
            return
        self._reset_calib(quiet=True)
        self._set_mode("calib")

    def _reset_calib(self, quiet: bool = False) -> None:
        self._calib = Calibration(self.kind)
        if self._canvas is not None:
            self._canvas.set_calib_points([])
        if self._mode == "calib":
            self._update_hint()
        if not quiet:
            self.status.emit("已清空标定，请重新点三个点")

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        if self._canvas is not None:
            self._canvas.set_cursor_mode(
                "none" if mode == "idle" else ("cross" if self.kind == "binary" else "tri")
            )
        self._btn_calib.setText(i18n.tr("结束标定" if mode == "calib" else "开始标定"))
        self._btn_region.setText(i18n.tr("结束标定" if mode == "boundary" else "开始新区域"))
        if mode == "calib":
            self._update_hint()
        elif mode == "boundary":
            self._hint.setText(i18n.tr(
                "在边界附近单击 → 自动吸附到最近的边界像素；右键点图删除最近的点"
            ))

    def _update_hint(self) -> None:
        hints = _CALIB_HINT.get(self.kind, _CALIB_HINT["binary"])
        done = len(self._calib.points)
        if done >= 3:
            self._hint.setText(i18n.tr("✅ 标定完成，可进入第 3 步"))
        else:
            self._hint.setText(i18n.tr(hints[done]))

    def _calib_data_for(self, index: int) -> Tuple[float, float]:
        """第 index 个标定点对应的数据坐标。"""
        if self.kind == "ternary":
            return ((1.0, 0.0), (0.0, 1.0), (0.0, 0.0))[index]
        x_min, x_max = self._x_min.value(), self._x_max.value()
        y_min, y_max = self._y_min.value(), self._y_max.value()
        return ((x_min, y_min), (x_max, y_min), (x_min, y_max))[index]

    # ---------------------------------------------------------------- 步骤 3
    def _region_mask(self) -> Optional[np.ndarray]:
        """标定出的坐标区掩码（没标定就返回 None，表示"整幅图"）。"""
        if self._original is None or not self._calib.ready:
            return None
        poly = self._calib.region_polygon()
        if poly is None:
            return None
        return polygon_mask(self._original.shape, poly)

    def _remove_grid(self) -> None:
        if self._original is None:
            self.status.emit("请先导入图像")
            return
        try:
            cleaned, lines = remove_grid_lines(
                self._original, kind=self.kind,
                threshold=int(self._threshold.value()),
                region=self._region_mask(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("去网格线失败：%s", exc)
            self.status.emit(f"去除网格线失败：{exc}")
            return
        self._working = cleaned
        if self._canvas is not None:
            self._canvas.set_image(cleaned)
        angles = sorted({round(float(line["angle"])) for line in lines})
        self._grid_info.setText(i18n.tr(
            f"已去除 {len(lines)} 条（方向 {angles}°）"
            if lines else "未发现网格线（可试着调高阈值）"
        ))
        self.status.emit(f"已去除 {len(lines)} 条网格线")

    def _restore_image(self) -> None:
        if self._original is None:
            return
        self._working = self._original.copy()
        if self._canvas is not None:
            self._canvas.set_image(self._working)
        self._grid_info.setText(i18n.tr("未处理"))
        self.status.emit("已恢复原图")

    # ---------------------------------------------------------------- 步骤 4
    def _start_region(self) -> None:
        if self._original is None:
            self.status.emit("请先导入图像")
            return
        if not self._calib.ready:
            self.status.emit("请先完成第 2 步标定")
            return
        if self._mode == "boundary":
            self._set_mode("idle")
            return
        self._current_points.clear()
        self._set_mode("boundary")
        self._sync_points()

    def _undo_point(self) -> None:
        if not self._current_points:
            return
        self._current_points.pop()
        self._sync_points()

    def _clear_points(self) -> None:
        self._current_points.clear()
        self._sync_points()

    def _sync_points(self) -> None:
        if self._canvas is not None:
            self._canvas.set_boundary_points(self._current_points)
        self._pt_info.setText(
            i18n.tr(f"边界点：{len(self._current_points)} 个（右键点图删除最近的点）")
        )

    def _finish_region(self) -> None:
        if len(self._current_points) < 3:
            self.status.emit("至少三个点才能围成区域")
            return
        # 数字前留一个空格：中文读作"区域 3"，英文片段替换后是"Region 3"
        default_label = i18n.tr(f"区域 {self._next_region_id}")
        label, ok = QInputDialog.getText(
            self, i18n.tr("区域标签"), i18n.tr("该区域的相（或相组合）名称："),
            text=default_label,
        )
        if not ok:
            return
        region = DigitizedRegion(
            region_id=self._next_region_id,
            label=str(label).strip() or default_label,
            points_px=list(self._current_points),
        )
        self._regions.append(region)
        self._next_region_id += 1
        self._current_points.clear()
        self._push_regions_to_canvas()
        self._sync_points()
        self._set_mode("idle")
        self.status.emit(f"已保存区域 {region.region_id}：{region.label}")

    def _push_regions_to_canvas(self) -> None:
        if self._canvas is None:
            return
        self._canvas.set_regions([
            {"points": r.points_px, "label": r.label} for r in self._regions
        ])

    # ---------------------------------------------------------------- 步骤 5
    def _generate(self) -> None:
        if not self._regions:
            self.status.emit("还没有标定好的区域")
            return
        if not self._calib.ready:
            self.status.emit("标定不完整，无法换算数据坐标")
            return
        try:
            frame = regions_to_frame(
                self._regions, self._calib,
                axis_x=self._axis_x.text().strip() or "X",
                axis_y=self._axis_y.text().strip() or "T",
                comp_names=[e.text().strip() or n for e, n in
                            zip(self._comp, ("A", "B", "C"))],
                step_x=self._step_x.value(),
                step_y=self._step_y.value(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("生成数字化数据失败：%s", exc)
            self.status.emit(f"生成失败：{exc}")
            return
        self._frame = frame
        self._fill_table(frame)
        self._data_info.setText(
            i18n.tr(f"共 {len(frame)} 个点，{len(self._regions)} 个区域")
        )
        self.status.emit(f"已生成 {len(frame)} 个数据点")

    def _fill_table(self, frame: pd.DataFrame) -> None:
        self._table.clear()
        self._table.setColumnCount(len(frame.columns))
        # 同高通量页：表头只翻显示，DataFrame / 导出的 CSV 仍是原始列名
        self._table.setHorizontalHeaderLabels(
            [i18n.tr(str(c)) for c in frame.columns]
        )
        self._table.setRowCount(len(frame))
        for row_idx, (_, row) in enumerate(frame.iterrows()):
            for col_idx, col in enumerate(frame.columns):
                value = row[col]
                text = "" if pd.isna(value) else str(value)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable)
                self._table.setItem(row_idx, col_idx, item)

    def _export_csv(self) -> None:
        if self._frame is None or self._frame.empty:
            self.status.emit("还没有可导出的数据，请先生成")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.tr("导出数字化数据"), "digitized.csv", i18n.tr("CSV 表格 (*.csv)")
        )
        if not path:
            return
        try:
            save_digitized_csv(self._frame, Path(path))
        except Exception as exc:  # noqa: BLE001
            self.status.emit(f"导出失败：{exc}")
            return
        self.status.emit(f"已导出 {path}")

    # ---------------------------------------------------------------- 画布事件
    def _on_canvas_clicked(self, px: float, py: float) -> None:
        try:
            if self._mode == "calib":
                self._add_calib_point(px, py)
            elif self._mode == "boundary":
                self._add_boundary_point(px, py)
        except Exception as exc:  # noqa: BLE001 - 槽里逃逸会 abort 进程
            logger.warning("数字化点击处理失败：%s", exc)
            self.status.emit(f"操作失败：{exc}")

    def _add_calib_point(self, px: float, py: float) -> None:
        index = len(self._calib.points)
        if index >= 3:
            self._calib.clear()
            index = 0
        data = self._calib_data_for(index)
        self._calib.add(px, py, data)
        if self._canvas is not None:
            self._canvas.set_calib_points([(p.px, p.py) for p in self._calib.points])
        self._update_hint()
        self.status.emit(f"标定点 {len(self._calib.points)}/3：像素 ({px:.0f}, {py:.0f})"
                         f" → 数据 ({data[0]:g}, {data[1]:g})")

    def _add_boundary_point(self, px: float, py: float) -> None:
        source = self._working if self._working is not None else self._original
        if source is None:
            return
        snapped = snap_to_boundary(source, px, py,
                                   threshold=int(self._threshold.value()))
        if snapped is None and self._calib.ready:
            # 兜底：坐标框常被第 3 步当网格线抹掉，而它正是贴边相区的边界
            poly = self._calib.region_polygon()
            if poly is not None:
                snapped = project_to_polygon(poly, px, py, tol=10.0)
        if snapped is None:
            self.status.emit("附近没找到边界（可放大视图或调高阈值）")
            return
        self._current_points.append(snapped)
        self._sync_points()
        self.status.emit(f"已吸附边界点 ({snapped[0]:.1f}, {snapped[1]:.1f})"
                         f"，共 {len(self._current_points)} 点")

    def _on_canvas_right_clicked(self, px: float, py: float) -> None:
        """右键删点：优先删边界点，其次删标定点。"""
        try:
            tol = 12.0
            if self._current_points:
                idx = self._nearest(self._current_points, px, py)
                if idx is not None and self._distance(self._current_points[idx], px, py) <= tol:
                    self._current_points.pop(idx)
                    self._sync_points()
                    self.status.emit("已删除一个边界点")
                    return
            if self._calib.points:
                pts = [(p.px, p.py) for p in self._calib.points]
                idx = self._nearest(pts, px, py)
                if idx is not None and self._distance(pts[idx], px, py) <= tol:
                    self._calib.points.pop(idx)
                    if self._canvas is not None:
                        self._canvas.set_calib_points(
                            [(p.px, p.py) for p in self._calib.points])
                    self._update_hint()
                    self.status.emit("已删除一个标定点")
        except Exception as exc:  # noqa: BLE001
            logger.warning("删除点失败：%s", exc)

    @staticmethod
    def _distance(point: Tuple[float, float], px: float, py: float) -> float:
        return float(np.hypot(point[0] - px, point[1] - py))

    def _nearest(self, points: Sequence[Tuple[float, float]],
                 px: float, py: float) -> Optional[int]:
        if not points:
            return None
        dists = [self._distance(p, px, py) for p in points]
        return int(np.argmin(dists))


__all__ = ["DigitizeTab"]

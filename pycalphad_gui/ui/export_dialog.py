"""导出对话框。

图像用"先选格式 → 再选保存路径"的两段式，避免用户填写后缀时出现大小写或
拼写问题；数据导出同理。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.exporter import suggest_export_name
from ..config import EXPORT_DATA_FORMATS, EXPORT_IMAGE_FORMATS
from .. import i18n

_IMAGE_FILTER = {
    "png": "PNG 位图 (*.png)",
    "svg": "SVG 矢量图 (*.svg)",
    "pdf": "PDF 文档 (*.pdf)",
    "jpg": "JPG 位图 (*.jpg)",
}

_DATA_FILTER = {
    "csv": "CSV 文本 (*.csv)",
    "xlsx": "Excel 工作簿 (*.xlsx)",
}


class ExportDialog(QDialog):
    """图像导出对话框。"""

    def __init__(self, parent=None, default_stem: str = "plot") -> None:
        super().__init__(parent)
        # 对话框按需 new 出来，主窗口的整树翻译扫不到它（父窗口不会遍历
        # 尚未构造的子对话框），所以标题必须在构造时显式翻一次。
        self.setWindowTitle(i18n.tr("导出图像"))
        self._stem = default_stem
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._fmt = QComboBox(self)
        for key in EXPORT_IMAGE_FORMATS:
            self._fmt.addItem(_IMAGE_FILTER[key], key)
        self._dpi = QSpinBox(self)
        self._dpi.setRange(72, 1200)
        self._dpi.setSingleStep(50)
        self._dpi.setValue(200)
        form.addRow("格式", self._fmt)
        form.addRow("分辨率 (DPI)", self._dpi)
        layout.addLayout(form)

        row = QHBoxLayout()
        self._path = QLineEdit(self)
        self._path.setReadOnly(True)
        self._path.setPlaceholderText("未选择保存位置")
        browse = QPushButton("浏览…", self)
        browse.clicked.connect(self._browse)
        row.addWidget(self._path, 1)
        row.addWidget(browse)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        # 用 itemData 取格式键：显示文本会被语言切换翻译，
        # 靠 split(" ")[-1] 反解后缀迟早会踩空
        fmt_key = self._fmt.currentData() or "png"
        default = suggest_export_name(self._stem, fmt_key)
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.tr("保存图像"), default, i18n.tr(self._fmt.currentText())
        )
        if path:
            self._path.setText(path)

    def _on_accept(self) -> None:
        if not self._path.text().strip():
            self._browse()
            if not self._path.text().strip():
                return
        self.accept()

    def selected_image_path(self) -> Optional[str]:
        text = self._path.text().strip()
        return text or None

    def dpi(self) -> int:
        return int(self._dpi.value())


class ExportDataTableDialog(ExportDialog):
    """数据导出对话框（CSV / XLSX）。"""

    def __init__(self, parent=None, default_stem: str = "data", formats: Optional[List[str]] = None) -> None:
        super().__init__(parent, default_stem)
        self.setWindowTitle(i18n.tr("导出数据"))
        # 替换格式下拉为数据格式
        self._fmt.clear()
        for key in formats or EXPORT_DATA_FORMATS:
            self._fmt.addItem(_DATA_FILTER.get(key, key), key)

    def selected_data_path(self) -> Optional[str]:
        return self.selected_image_path()


def pick_save_path(parent, stem: str, fmt_key: str, kind: str = "image") -> Optional[Path]:
    """单文件保存路径选择，供脚本化调用。"""
    from PyQt6.QtWidgets import QFileDialog

    if kind == "image":
        default = suggest_export_name(stem, fmt_key)
        path, _ = QFileDialog.getSaveFileName(
            parent, i18n.tr("保存图像"), default, i18n.tr(_IMAGE_FILTER.get(fmt_key, ""))
        )
    else:
        default = suggest_export_name(stem, fmt_key)
        path, _ = QFileDialog.getSaveFileName(
            parent, i18n.tr("保存数据"), default, i18n.tr(_DATA_FILTER.get(fmt_key, ""))
        )
    return Path(path) if path else None

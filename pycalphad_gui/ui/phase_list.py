"""可排除的相列表。

相的启用/排除是几乎所有 pycalphad 计算的公共入参，因此这里只负责维护
「启用集合」这一唯一数据源，其余模块一律读取 :meth:`enabled_phases`。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.database_manager import PhaseInfo
from .. import i18n


class PhaseListWidget(QWidget):
    """相列表控件。"""

    #: 启用集合变化时发出，参数为启用相名列表
    selection_changed = pyqtSignal(list)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._infos: Dict[str, PhaseInfo] = {}
        self._filter = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("搜索相名…")
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        self._list = QListWidget(self)
        self._list.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._list, 1)

        row = QHBoxLayout()
        for text, slot in (
            ("全选", self.select_all),
            ("全不选", self.select_none),
            ("反选", self.invert),
        ):
            btn = QPushButton(text, self)
            btn.clicked.connect(slot)
            row.addWidget(btn)
        layout.addLayout(row)

    # ---------------------------------------------------------------- 数据
    def set_phases(self, infos: Dict[str, PhaseInfo]) -> None:
        """载入数据库的相信息（会保留已有的启用状态）。"""
        previous = set(self.enabled_phases())
        self._infos = dict(infos)
        self._reload(previous)

    def _reload(self, previous_enabled: Sequence[str]) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for name in sorted(self._infos):
            info = self._infos[name]
            item = QListWidgetItem(self._list)
            item.setText(i18n.tr(
                f"{name}  ·  {info.n_sublattices} 子格子 · {info.model_type}"
            ))
            item.setToolTip(self._tooltip(name))
            item.setData(Qt.ItemDataRole.UserRole, name)
            checked = name in previous_enabled if previous_enabled else True
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._list.addItem(item)
        self._list.blockSignals(False)
        self._apply_filter()

    def _tooltip(self, name: str) -> str:
        info = self._infos.get(name)
        if info is None or not info.constituents:
            return name
        parts = " / ".join("+".join(sub) for sub in info.constituents)
        return f"{name}\n子格子构成：{parts}"

    def _apply_filter(self, _: str = "") -> None:
        text = self._search.text().strip().lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(bool(text) and text not in name.lower())

    # ---------------------------------------------------------------- 事件
    def _on_item_changed(self, item: QListWidgetItem) -> None:
        self.selection_changed.emit(self.enabled_phases())

    # ---------------------------------------------------------------- 接口
    def enabled_phases(self) -> List[str]:
        """当前启用的相。"""
        out = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def set_enabled(self, names: Sequence[str]) -> None:
        """程序化设置启用集合。"""
        target = set(names)
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setCheckState(
                Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in target
                else Qt.CheckState.Unchecked
            )
        self._list.blockSignals(False)
        self.selection_changed.emit(self.enabled_phases())

    def select_all(self) -> None:
        self._set_all(Qt.CheckState.Checked)

    def select_none(self) -> None:
        self._set_all(Qt.CheckState.Unchecked)

    def invert(self) -> None:
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setCheckState(
                Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                else Qt.CheckState.Checked
            )
        self._list.blockSignals(False)
        self.selection_changed.emit(self.enabled_phases())

    def _set_all(self, state: Qt.CheckState) -> None:
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)
        self._list.blockSignals(False)
        self.selection_changed.emit(self.enabled_phases())

    @property
    def excluded_phases(self) -> List[str]:
        """被排除的相名，按字母序。"""
        return sorted(set(self._infos) - set(self.enabled_phases()))

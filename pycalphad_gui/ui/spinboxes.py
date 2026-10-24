"""显示位数与存储精度分离的数字框。

QDoubleSpinBox 的 ``decimals`` 同时决定"显示几位"和"取值精度"——设 1 位
显示，用户输入 300.25 会被直接改写成 300.3，**丢精度**。这里把两者拆开：
``decimals`` 保持原样（存储/参与计算的精度不变），``textFromValue`` 按配置
的位数渲染，于是：

- 温度默认显示 1 位（300.0、1500.0、20.0）
- 成分默认显示 3 位（0.000、1.000、0.020）
- 输入时多打几位照样接受（四舍五入到存储精度，不弹错）
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from PyQt6.QtGui import QValidator
from PyQt6.QtCore import QLocale
from PyQt6.QtWidgets import QDoubleSpinBox, QWidget


class DisplaySpin(QDoubleSpinBox):
    """显示位数（display_decimals）与存储精度（decimals）分离的数字框。"""

    def __init__(
        self, display_decimals: int = 3, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self._display_decimals = display_decimals

    def display_decimals(self) -> int:
        """当前显示位数。"""
        return self._display_decimals

    def set_display_decimals(self, n: int) -> None:
        """切换显示位数并刷新文本。

        ``setValue(相同值)`` 会被 Qt 短路（值没变就不刷新），切位数后
        只能手动重写 lineEdit 文本；失焦/回车时 interpret 会用同一值
        重新走一遍 textFromValue，显示自然对齐。
        """
        if n == self._display_decimals:
            return
        self._display_decimals = n
        self.lineEdit().setText(self.textFromValue(self.value()))

    def textFromValue(self, value: float) -> str:  # noqa: N802
        # 用十进制半进位（ROUND_HALF_UP），跟人的直觉一致：
        # f-string 的 .1f 是银行家舍入，300.25 会显示成 300.2
        q = Decimal(repr(value)).quantize(
            Decimal(1).scaleb(-self._display_decimals), rounding=ROUND_HALF_UP
        )
        return f"{q:.{self._display_decimals}f}"

    def validate(self, text: str, pos: int):  # noqa: N802
        # 放行比存储位数更多的小数位：Qt 默认把超位数输入标成 Intermediate，
        # 回车/失焦时**静默丢弃**（实测输 0.333333 直接弹回 0.0）。这里一律
        # Acceptable，提交交给 valueFromText 按存储精度舍入；乱码由解析失败
        # 兜底（保持原值），范围仍由 setValue 的钳制保证。
        return QValidator.State.Acceptable, text, pos

    def valueFromText(self, text: str) -> float:  # noqa: N802
        t = text
        pre, suf = self.prefix(), self.suffix()
        if pre and t.startswith(pre):
            t = t[len(pre):]
        if suf and t.endswith(suf):
            t = t[: -len(suf)]
        value, ok = QLocale().toDouble(t.strip())
        return value if ok else self.value()

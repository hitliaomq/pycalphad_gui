"""界面双语支持（中文 ⇄ 英文），**默认英文**。

设计要点
--------
1. **只维护一份词典**（中文 → 英文）。反向 ``EN2ZH`` 自动生成，
   新增词条时只需写一行中文→英文。
2. ``tr()`` 是**幂等**的：``tr(tr(x)) == tr(x)``。因为只有当文本属于"另一种
   语言"时才查表（英文模式下查 ZH2EN，中文模式下查 EN2ZH），已经是目标语言
   的文本不会被二次翻译。这让"启动后整树扫一遍"和"新建控件时再翻一次"可以共存。
3. 本模块**顶层不 import PyQt6**，因此 ``tests/test_smoke.py`` 这类无界面脚本
   也能安全导入；只有 ``apply_to()`` / ``apply_to_figure()`` 在函数内部延迟导入。
4. 采用"整棵控件树遍历翻译"而不是给几千处字符串逐个包 ``tr()``：
   已有界面代码不用动，新增词只要进词典即可生效。

不翻译什么
----------
* **纯数据**：元素符号、相名（``BCC_A2``）、颜色名、数值、材料名、用户输入的
  标注文字。靠"不含汉字直接返回"天然免疫——它们本来就不在词典里。
* **QSS 样式表**：``theme.py`` 里的样式串虽然在 Python 层面也是字符串，
  但它是样式而不是文案，也不参与控件文本，永远不会被扫到。
* **语言按钮自身**：语言自称（``English`` / ``中文``）不收录，否则切一次语言
  按钮上的字就跟着变了。
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

__all__ = [
    "LANGS", "LANG_NAMES", "DEFAULT_LANG",
    "lang", "set_lang", "tr", "tr_to", "has_cjk", "known",
    "apply_to", "apply_to_figure", "on_change", "notify_changed",
    "settings_key", "load_saved_lang", "save_lang",
]

#: 支持的语言（顺序即语言按钮菜单里的顺序）
LANGS = ("en", "zh")
#: 语言自称——**故意不放进词典**，保证语言按钮上的字恒定
LANG_NAMES: Dict[str, str] = {"en": "English", "zh": "中文"}
#: 默认语言：用户要求默认英文
DEFAULT_LANG = "en"

_current: str = DEFAULT_LANG
_listeners: List = []


# ---------------------------------------------------------------------------
# 词典装配
# ---------------------------------------------------------------------------
from .i18n_zh_en_core import CORE_ZH_EN      # noqa: E402  引擎消息 / 诊断 / 元素名
from .i18n_zh_en_ui import UI_ZH_EN          # noqa: E402  界面文案
from .i18n_zh_en_macro import MACRO_ZH_EN    # noqa: E402  宏命令 / 宏页面

#: 中文原文 → 英文译文（后装配的词典优先级更高，可覆盖同名词条）
_ZH_EN: Dict[str, str] = {}
_ZH_EN.update(CORE_ZH_EN)
_ZH_EN.update(UI_ZH_EN)
_ZH_EN.update(MACRO_ZH_EN)

#: 反向词典（自动生成）。同一句英文对应多个中文时只保留首个——语义等价。
#: 长度为 4 以下的英文值不建反向（``"，" → ", "`` 这类标点片段若进了反向表，
#: 切回中文时会去咬英文句子里正常的逗号，属于自伤）。
_EN_ZH: Dict[str, str] = {}
for _zh, _en in _ZH_EN.items():
    if _en and len(_en) >= 4 and _en not in _EN_ZH:
        _EN_ZH[_en] = _zh

#: 片段替换用的键：按长度降序，长串优先（否则"模量"会抢在"剪切模量"前面）。
#:
#: 只有**长度 ≥ 2** 的键才允许进片段表，外加下面这组标点／括号。原因：
#: ``"相"``、``"是"``、``"钛"`` 这类单字键一旦参与片段替换，就会去咬任何一句
#: 没收录的中文（"这是…" → 被 "是" 命中），把整句话搞花。标点是例外，
#: 它们本来就是拼句子的粘合剂，且正反向都有对称条目。
_PUNCT_KEYS = frozenset("（）「」『』，、：；。·")
_ZH_KEYS: List[str] = sorted(
    (k for k in _ZH_EN if len(k) >= 2 or k in _PUNCT_KEYS),
    key=len, reverse=True,
)
#: 反向片段：英文键太短的（``", "``、``") "``）同样不许进，
#: 否则切回中文时会把英文句子里正常的标点换掉。
_EN_KEYS: List[str] = sorted(_EN_ZH, key=len, reverse=True)


# ---------------------------------------------------------------------------
# 基础 API
# ---------------------------------------------------------------------------
def lang() -> str:
    """当前界面语言（``'en'`` / ``'zh'``）。"""
    return _current


def set_lang(value: str) -> str:
    """设置当前语言，非法值回退到默认。返回实际生效的语言。"""
    global _current
    _current = value if value in LANGS else DEFAULT_LANG
    return _current


def has_cjk(text: str) -> bool:
    """文本是否含汉字（用来判断"这段文本属于哪种语言"）。"""
    if not text:
        return False
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            return True
    return False


def known(text: str) -> bool:
    """该文本是否在词典里（自检 / 调试用）。"""
    return text in _ZH_EN or text in _EN_ZH


def _frag(text: str, keys: List[str], mapping: Dict[str, str]) -> str:
    """片段级兜底：整串没收录时，把其中已收录的片段逐个替换掉。

    照顾 ``f"已载入 {name}｜元素 {n} 个"`` 这类拼接串——整串含变量、不可能
    进词典，但片段是固定文案。按 key 长度降序替换，保证长串优先。
    """
    out = text
    for k in keys:
        if k in out:
            out = out.replace(k, mapping[k])
    return out


def tr_to(text: str, target: str) -> str:
    """把 text 翻译成 target 语言；查不到就原样返回（数据永远不会被误伤）。

    两级匹配：先整串精确命中，再退化为片段替换。已经是目标语言的文本会
    **立即返回**，因此纯数据（数值、相名、元素符号）几乎零开销。
    """
    if not text or not isinstance(text, str):
        return text
    if target == "en":
        if not has_cjk(text):          # 无汉字 = 已经是英文或纯数据
            return text
        if text in _ZH_EN:
            value = _ZH_EN[text]
            return text if value is None else value
        return _frag(text, _ZH_KEYS, _ZH_EN)
    if has_cjk(text):                  # 要中文，却已经是中文
        return text
    if text in _EN_ZH:
        return _EN_ZH[text]
    return _frag(text, _EN_KEYS, _EN_ZH)


def tr(text: str, target: Optional[str] = None) -> str:
    """把 text 翻译成当前（或指定）语言。幂等：``tr(tr(x)) == tr(x)``。"""
    return tr_to(text, target or _current)


def tr_all(texts: Iterable[str], target: Optional[str] = None) -> List[str]:
    return [tr(t, target) for t in texts]


# ---------------------------------------------------------------------------
# 语言变更通知（让页面刷新"代码生成"的内容 / 重绘图表）
# ---------------------------------------------------------------------------
def on_change(func) -> None:
    """注册回调，语言切换后会收到新语言代码。"""
    if func not in _listeners:
        _listeners.append(func)


def notify_changed(new_lang: str) -> None:
    for fn in list(_listeners):
        try:
            fn(new_lang)
        except Exception:  # noqa: BLE001 - 单个页面刷新失败不该阻断其余页面
            import traceback

            traceback.print_exc()


# ---------------------------------------------------------------------------
# 持久化（QSettings）
# ---------------------------------------------------------------------------
SETTINGS_ORG = "pyCalphad GUI"
SETTINGS_APP = "pyCalphad GUI"
#: QSettings 里存语言的键
SETTINGS_KEY = "ui/language"


def settings_key() -> str:
    return SETTINGS_KEY


def load_saved_lang() -> str:
    """读取上次选的语言；读不到 / 非法值 → 默认英文。"""
    try:
        from PyQt6.QtCore import QSettings

        value = QSettings(SETTINGS_ORG, SETTINGS_APP).value(SETTINGS_KEY, "", type=str)
    except Exception:  # noqa: BLE001 - 设置读不出来不该影响启动
        return DEFAULT_LANG
    return value if value in LANGS else DEFAULT_LANG


def save_lang(code: str) -> None:
    """记住用户选的语言（失败静默——写设置失败不该打断切换动作）。"""
    try:
        from PyQt6.QtCore import QSettings

        QSettings(SETTINGS_ORG, SETTINGS_APP).setValue(SETTINGS_KEY, code)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# 控件树遍历翻译（依赖 Qt 的部分一律延迟 import）
# ---------------------------------------------------------------------------
def apply_to(root, target: Optional[str] = None) -> int:
    """递归翻译 root 及其所有子控件的可见文本，返回被改动的字符串条数。

    只翻译"词典里有的文本"，所以数值、相名、元素符号等数据不会被误伤。
    """
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QAbstractSpinBox,
        QComboBox,
        QDockWidget,
        QGroupBox,
        QLabel,
        QLineEdit,
        QListWidget,
        QMenu,
        QPlainTextEdit,
        QStatusBar,
        QTabWidget,
        QTableWidget,
        QTextEdit,
        QToolBox,
        QWidget,
    )

    tgt = target or _current
    n = 0

    def _set(obj, getter: str, setter: str) -> None:
        nonlocal n
        try:
            old = getattr(obj, getter)()
        except Exception:  # noqa: BLE001 - 个别控件没有该属性，跳过
            return
        if not isinstance(old, str) or not old:
            return
        new = tr_to(old, tgt)
        if new != old:
            getattr(obj, setter)(new)
            n += 1

    widgets = [root]
    try:
        widgets += list(root.findChildren(QWidget))
    except Exception:  # noqa: BLE001
        pass

    for w in widgets:
        # 改文本会触发 textChanged / currentTextChanged 等信号，一律屏蔽：
        # 否则翻译本身会引发一轮（而且还用着旧数据的）重算。
        blocked = w.blockSignals(True)
        try:
            if isinstance(w, QStatusBar):
                continue                      # 状态栏是动态消息，由主窗口单独管
            if isinstance(w, QLabel) and not w.property("i18nSkipText"):
                _set(w, "text", "setText")
            if isinstance(w, QAbstractButton):
                _set(w, "text", "setText")
            if isinstance(w, QGroupBox):
                _set(w, "title", "setTitle")
            if isinstance(w, QLineEdit):
                _set(w, "placeholderText", "setPlaceholderText")
            if isinstance(w, QAbstractSpinBox):
                _set(w, "prefix", "setPrefix")
                _set(w, "suffix", "setSuffix")
                # QSpinBox/QDoubleSpinBox 在 minimum 时显示的"特殊值文本"
                # （ESPEI 页 Ridge α 的"关闭（普通最小二乘）"），不在
                # text()/suffix() 里，漏了它就会出现"别的都翻了就它没翻"
                _set(w, "specialValueText", "setSpecialValueText")
            if isinstance(w, QComboBox) and not w.property("i18nSkipText"):
                for i in range(w.count()):
                    old = w.itemText(i)
                    if not old:
                        continue
                    new = tr_to(old, tgt)
                    if new != old:
                        w.setItemText(i, new)
                        n += 1
            if isinstance(w, QTabWidget):
                for i in range(w.count()):
                    for getter, setter in (("tabText", "setTabText"),
                                           ("tabToolTip", "setTabToolTip")):
                        n += _tab_set(w, i, getter, setter, tgt)
            if isinstance(w, QTableWidget):
                n += _apply_table(w, tgt)
            if isinstance(w, QListWidget):
                for i in range(w.count()):
                    it = w.item(i)
                    if it is not None:
                        old = it.text()
                        new = tr_to(old, tgt)
                        if new != old:
                            it.setText(new)
                            n += 1
            if isinstance(w, (QTextEdit, QPlainTextEdit)):
                # 多行编辑框的占位提示不在 text() 里，单独翻一次，
                # 否则英文模式下会留下一句中文的"在此编写宏命令…"
                _set(w, "placeholderText", "setPlaceholderText")
                # 日志/说明框：只翻"尚未运行 / 已就绪"这类静态占位文本，
                # 已经滚了很多行的运行日志不碰（里面是数据）。
                if not w.isReadOnly() or w.toPlainText().count("\n") == 0:
                    old = w.toPlainText()
                    new = tr_to(old, tgt)
                    if new != old:
                        w.setPlainText(new)
                        n += 1
            if isinstance(w, QToolBox):
                for i in range(w.count()):
                    old = w.itemText(i)
                    new = tr_to(old, tgt)
                    if new != old:
                        w.setItemText(i, new)
                        n += 1
            _set(w, "toolTip", "setToolTip")
            _set(w, "statusTip", "setStatusTip")
            _set(w, "whatsThis", "setWhatsThis")
            if isinstance(w, QDockWidget):
                # 停靠面板标题：**停靠状态**下 isWindow() 是 False，
                # 走不到下面的 windowTitle 分支 ——「元素与相」「计算」
                # 这两块就是这么漏掉的（用户实测）
                _set(w, "windowTitle", "setWindowTitle")
            elif w.isWindow():
                _set(w, "windowTitle", "setWindowTitle")
        finally:
            w.blockSignals(blocked)

    # 菜单里的 QAction 不是 QWidget，得单独走一遍
    try:
        for act in root.findChildren(QAction):
            _set(act, "text", "setText")
            _set(act, "toolTip", "setToolTip")
        for menu in root.findChildren(QMenu):
            _set(menu, "title", "setTitle")
    except Exception:  # noqa: BLE001
        pass
    return n


def _tab_set(tabs, i: int, getter: str, setter: str, tgt: str) -> int:
    """翻译标签页的文本 / tooltip；返回是否改动（0 或 1）。"""
    try:
        old = getattr(tabs, getter)(i)
    except Exception:  # noqa: BLE001
        return 0
    if not isinstance(old, str) or not old:
        return 0
    new = tr_to(old, tgt)
    if new == old:
        return 0
    getattr(tabs, setter)(i, new)
    return 1


def _apply_table(tbl, tgt: str) -> int:
    """表头 + 单元格。只翻词典里有的文本，数值单元格天然不受影响。"""
    n = 0
    hh, vh = tbl.horizontalHeaderItem, tbl.verticalHeaderItem
    for i in range(tbl.columnCount()):
        it = hh(i)
        if it is not None:
            old = it.text()
            new = tr_to(old, tgt)
            if new != old:
                it.setText(new)
                n += 1
    for j in range(tbl.rowCount()):
        it = vh(j)
        if it is not None:
            old = it.text()
            new = tr_to(old, tgt)
            if new != old:
                it.setText(new)
                n += 1
    for j in range(tbl.rowCount()):
        for i in range(tbl.columnCount()):
            it = tbl.item(j, i)
            if it is None:
                continue
            old = it.text()
            if not old:
                continue
            new = tr_to(old, tgt)
            if new != old:
                it.setText(new)
                n += 1
    return n


def apply_to_figure(fig, target: Optional[str] = None) -> int:
    """翻译一张 matplotlib Figure 上的文字（轴题 / 标题 / 刻度 / 图例）。

    matplotlib 的 ``Text`` 对象不是 QWidget，整树遍历扫不到它们，所以绘图
    结果需要单独走一遍。**只翻词典里有的文本**：刻度数字、相名、用户自己
    写的标注都原样保留。

    刻意不碰 ``ax.texts``（用户放置的标注）——那是用户输入的数据；
    也不碰 ``annotate`` 落下的 tie line 标签（默认是相名，ASCII）。
    """
    tgt = target or _current
    n = 0

    def _set(obj, getter: str, setter: str) -> None:
        nonlocal n
        try:
            old = getattr(obj, getter)()
        except Exception:  # noqa: BLE001
            return
        if not isinstance(old, str) or not old:
            return
        new = tr_to(old, tgt)
        if new != old:
            getattr(obj, setter)(new)
            n += 1

    try:
        axes_list = list(fig.axes)
    except Exception:  # noqa: BLE001
        return 0
    for ax in axes_list:
        _set(ax, "get_title", "set_title")
        _set(ax, "get_xlabel", "set_xlabel")
        _set(ax, "get_ylabel", "set_ylabel")
        try:
            legend = ax.get_legend()
        except Exception:  # noqa: BLE001
            legend = None
        if legend is not None:
            for text in legend.get_texts():
                old = text.get_text()
                new = tr_to(old, tgt)
                if new != old:
                    text.set_text(new)
                    n += 1
        for axis in (ax.xaxis, ax.yaxis):
            for tick in axis.get_major_ticks():
                # 注意：Tick.get_label() 继承自 Artist，返回的是 **str**
                # （刻度的 label 属性），真正的刻度文本是 tick.label1 ——
                # 拿它调 .get_text() 会直接 AttributeError
                label = getattr(tick, "label1", None)
                if label is None:
                    continue
                old = label.get_text()
                new = tr_to(old, tgt)
                if new != old:
                    label.set_text(new)
                    n += 1
    for text in getattr(fig, "texts", ()):
        old = text.get_text()
        new = tr_to(old, tgt)
        if new != old:
            text.set_text(new)
            n += 1
    return n

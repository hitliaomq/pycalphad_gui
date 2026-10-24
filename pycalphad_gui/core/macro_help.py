"""宏命令帮助与补全词表（纯数据，不依赖 Qt）。

交互式命令面板需要两种帮助：不带参数的 ``?`` 给出命令总览，``命令 ?``
给出单条命令的用法、说明和示例。这里把文案与 ``macro_engine`` 的别名表放在
一起，保证帮助、语法高亮和补全不会各说各话。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .macro_engine import _COMMAND_ALIASES


@dataclass(frozen=True)
class CommandHelp:
    """一条宏命令的帮助条目。"""

    name: str
    usage: str
    summary: str
    detail: str = ""
    examples: Tuple[str, ...] = ()


#: 帮助顺序 = 宏里常见的书写顺序
_HELP: Dict[str, CommandHelp] = {
    "OPEN": CommandHelp(
        "OPEN",
        "OPEN <TDB/DAT>",
        "载入热力学数据库",
        "路径相对当前宏文件所在目录解析，找不到时会向上查找父目录。"
        "载入后扫描条件与绘图选项会重置。",
        ("OPEN database/alzn_mey.tdb",),
    ),
    "ELEMENTS": CommandHelp(
        "ELEMENTS",
        "ELEMENTS <element> [element ...]",
        "选择参与计算的元素",
        "元素符号大小写不敏感；写 * 或 ALL 表示全选。",
        ("ELEMENTS AL ZN",),
    ),
    "PHASES": CommandHelp(
        "PHASES",
        "PHASES <phase> [phase ...]",
        "指定参与计算的相",
        "写 * 或 ALL 表示全部相；相名前加 - 可从当前选择中移除。",
        ("PHASES LIQUID FCC_A1",),
    ),
    "EXCLUDE": CommandHelp(
        "EXCLUDE",
        "EXCLUDE <phase> [phase ...]",
        "从计算中排除相",
        "被排除的相不参与平衡计算，效果等同在 PHASES 里写 -相名。",
        ("EXCLUDE BCC_A2",),
    ),
    "SWEEP": CommandHelp(
        "SWEEP",
        "SWEEP <target> <start> <stop> <step>",
        "设置扫描轴",
        "目标可以是 T、P 或元素符号；步长符号决定扫描方向，最多 5000 个采样点。",
        ("SWEEP ZN 0 1 0.02",),
    ),
    "FIXED": CommandHelp(
        "FIXED",
        "FIXED <var>=<value> [var=value ...]",
        "设置固定条件",
        "变量可以是 T、P、N 或 X(元素)=分数，多个条件用空格分隔。",
        ("FIXED T=600 P=101325",),
    ),
    "OPTIONS": CommandHelp(
        "OPTIONS",
        "OPTIONS <key>=<value> [key=value ...]",
        "设置绘图选项",
        "可用键：TIELINES、LABELS、GRID、AUTO-START、STEP-Y、FIG-SIZE。",
        ("OPTIONS TIELINES=OFF GRID=ON",),
    ),
    "DIAGRAM": CommandHelp(
        "DIAGRAM",
        "DIAGRAM <类型>",
        "计算并绘制相图",
        "类型：BINARY、TERNARY、EQPLOT-BINARY、EQPLOT-TERNARY、STEP、ISOPLETH。"
        "计算使用 SWEEP 与 FIXED 设定的条件。",
        ("DIAGRAM BINARY",),
    ),
    "PROPERTY": CommandHelp(
        "PROPERTY",
        "PROPERTY <property> VS <axis> FROM <start> TO <stop> STEP <step>",
        "计算并绘制属性曲线",
        "属性可以是 GM、HM、SM、CPM、NP、X(相,元素)、degree_of_ordering(相) "
        "或 sitefraction(相)；用 T=、X=、X(元素)= 固定其它条件。",
        ("PROPERTY GM VS ZN FROM 0 TO 1 STEP 0.02 T=600",),
    ),
    "SCHEIL": CommandHelp(
        "SCHEIL",
        "SCHEIL X(<element>)=<fraction> [START-T=<T>] [STEP-T=<step>]",
        "执行 Scheil 凝固模拟",
        "还可用 STOP=、ADAPTIVE=、LIQUID=、METHOD= 控制过程；结果可导出为 CSV。",
        ("SCHEIL X(ZN)=0.3 START-T=850 STEP-T=1",),
    ),
    "EQUILIBRIUM": CommandHelp(
        "EQUILIBRIUM",
        "EQUILIBRIUM X(<element>)=<fraction> [START-T=<T>] [STEP-T=<step>]",
        "执行平衡凝固模拟",
        "参数与 SCHEIL 相同，按平衡条件逐步降温，用来和 Scheil 结果对照。",
        ("EQUILIBRIUM X(ZN)=0.3 START-T=850 STEP-T=1",),
    ),
    "ESPEI": CommandHelp(
        "ESPEI",
        "ESPEI <GENERATE|MCMC|CHECK> [key=value ...]",
        "运行 ESPEI 参数拟合",
        "常用键：PHASE-MODELS、DATASETS、INPUT-DB、OUTPUT-DB、ITERATIONS、CORES；"
        "数据集标签用 TAGS=dft:-idmix,-mag;estimated-entropy:-idmix,-mag,weight=0.1，"
        "AICc 惩罚用 AICC=LIQUID:HM=1.4,LIQUID:SM=1.4。",
        ("ESPEI GENERATE PHASE-MODELS=phase_models.json DATASETS=input-data "
         "AICC=LIQUID:HM=1.4,LIQUID:SM=1.4",),
    ),
    "HT": CommandHelp(
        "HT",
        "HT [OUTPUTS=<metrics>] [PARALLEL=<threads>]",
        "运行高通量平衡计算",
        "至少需要一个 SWEEP；输出指标可用 stable_phases、gm_min、n_phases 等。",
        ("HT OUTPUTS=stable_phases,gm_min PARALLEL=4",),
    ),
    "EXPORT": CommandHelp(
        "EXPORT",
        "EXPORT FIGURE <file> | EXPORT DATA <file>",
        "导出最近的图像或数据表",
        "图像支持 PNG / SVG / PDF / JPG，数据支持 CSV / XLSX；"
        "相对路径按宏文件所在目录解析。",
        ("EXPORT FIGURE output/al_zn.png",),
    ),
    "PRINT": CommandHelp(
        "PRINT",
        "PRINT <text>",
        "在输出中打印文本",
        "支持 $变量 替换，适合在宏里输出中间状态；"
        "含等号的文本请用引号包住。",
        ('PRINT "T=$temp"',),
    ),
    "SET": CommandHelp(
        "SET",
        "SET <name> <value>",
        "定义宏变量",
        "也可以在行首写 $名称 = 值，之后用 $名称 引用。",
        ("SET temp 850",),
    ),
    "INCLUDE": CommandHelp(
        "INCLUDE",
        "INCLUDE <macro file>",
        "执行另一个宏文件",
        "相对路径按当前宏文件所在目录解析，最多嵌套 8 层。",
        ("INCLUDE common/load.pcm",),
    ),
    "RESET": CommandHelp(
        "RESET",
        "RESET",
        "重置条件与绘图选项",
        "清空扫描、固定条件与绘图选项，保留数据库、元素、相和变量。",
        ("RESET",),
    ),
    "SHOW": CommandHelp(
        "SHOW",
        "SHOW [ALL|DATABASE|ELEMENTS|PHASES|CONDITIONS]",
        "显示当前会话状态",
        "不带参数时显示全部状态，适合在交互式命令面板里检查当前条件。",
        ("SHOW",),
    ),
}

_OVERVIEW_HEADER = "宏命令一览（输入 ? 显示本页，输入 命令 ? 查看详细帮助）"
_OVERVIEW_FOOTER = (
    "其它语法：$变量、# 或 // 注释、\\ 续行、INCLUDE 引用宏文件。"
    "命令大小写不敏感。"
)

#: 命令 → 别名（由解释器的别名表反推，供帮助与补全共用）
_ALIASES: Dict[str, List[str]] = {name: [] for name in _HELP}
for _alias, _target in _COMMAND_ALIASES.items():
    if _target in _ALIASES:
        _ALIASES[_target].append(_alias)
for _names in _ALIASES.values():
    _names.sort()


def command_names() -> List[str]:
    """全部正式命令名（帮助顺序）。"""
    return list(_HELP)


def aliases_for(command: str) -> List[str]:
    """某条命令的别名（大小写不敏感，未知命令返回空表）。"""
    name = command.strip().upper()
    name = _COMMAND_ALIASES.get(name, name)
    return list(_ALIASES.get(name, ()))


def completion_words() -> List[str]:
    """第一列可补全的词：正式命令 + 别名 + 帮助符号。"""
    words = set(_HELP) | set(_COMMAND_ALIASES) | {"?"}
    return sorted(words)


#: DIAGRAM 的推荐写法（补全只给这几种，别名仍可直接输入）
_DIAGRAM_WORDS = (
    "BINARY", "TERNARY", "EQPLOT-BINARY", "EQPLOT-TERNARY", "STEP", "ISOPLETH",
)


def diagram_types() -> List[str]:
    """DIAGRAM 补全用的类型名（正式写法，不含内部类型与短别名）。"""
    return list(_DIAGRAM_WORDS)


def help_overview() -> str:
    """``?`` 的总览：每条命令一行语法与说明。"""
    width = max(len(name) for name in _HELP) + 2
    lines = [_OVERVIEW_HEADER, ""]
    for item in _HELP.values():
        lines.append(f"{item.name:<{width}}{item.summary}")
    lines.extend(["", _OVERVIEW_FOOTER])
    return "\n".join(lines)


def help_for(command: str) -> Optional[str]:
    """``命令 ?`` 的详细帮助；未知命令返回 ``None``。"""
    query = command.strip().upper()
    name = _COMMAND_ALIASES.get(query, query)
    item = _HELP.get(name)
    if item is None:
        return None
    title = name
    aliases = _ALIASES.get(name) or []
    if aliases:
        title += "（别名 " + " / ".join(aliases) + "）"
    lines = [title, "用法：" + item.usage, "说明：" + item.summary]
    if item.detail:
        lines.append(item.detail)
    if item.examples:
        lines.append("示例：")
        lines.extend("  " + example for example in item.examples)
    return "\n".join(lines)


def help_request(text: str) -> Tuple[bool, Optional[str], str]:
    """解析交互式输入是否是帮助请求。

    返回 ``(是否帮助请求, 帮助文本, 命令名)``。支持的写法：``?``、
    ``? OPEN``、``OPEN ?``；未知命令的帮助文本为 ``None``，命令名留给界面
    拼"未知命令"提示。普通命令返回 ``(False, None, "")``。
    """
    stripped = text.strip()
    if not stripped:
        return False, None, ""
    if stripped == "?":
        return True, help_overview(), ""
    if stripped.startswith("?"):
        query = stripped[1:].strip()
        if not query:
            return True, help_overview(), ""
        name = query.split()[0]
        return True, help_for(name), name
    if stripped.endswith("?"):
        query = stripped[:-1].strip()
        if not query:
            return True, help_overview(), ""
        name = query.split()[0]
        return True, help_for(name), name
    return False, None, ""


__all__ = [
    "CommandHelp",
    "aliases_for",
    "command_names",
    "completion_words",
    "diagram_types",
    "help_for",
    "help_overview",
    "help_request",
]

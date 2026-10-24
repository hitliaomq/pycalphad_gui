"""计算异常的中文诊断。

pycalphad 抛出的异常信息偏工程英文，直接弹窗对材料背景用户并不友好。
这里把高频异常映射为"原因 + 怎么办"，完整堆栈仍然写日志，不丢失可排查性。
"""
from __future__ import annotations

import logging
import traceback
from typing import Union

logger = logging.getLogger(__name__)


class CalculationError(Exception):
    """GUI 层统一的失败类型，携带面向用户的诊断文本。"""

    def __init__(self, user_message: str, detail: str = ""):
        super().__init__(user_message if not detail else f"{user_message}（{detail}）")
        self.user_message = user_message
        self.detail = detail


# ---------------------------------------------------------------- 匹配规则
#: (匹配串, 用户可读的诊断, 解决建议)
_RULES: tuple = (
    (
        "requires exactly one composition coordinate and one potential coordinate",
        "二元相图需要「恰好 1 个变化的组分」和「恰好 1 个变化的外部条件（温度或压力）」。",
        "请检查条件面板：组分扫描与温度/压力扫描各只能有一个.",
    ),
    (
        "requires exactly two composition coordinates",
        "三元等温截面需要「恰好 2 个变化的组分」，且温度、压力必须固定为单值。",
        "请把温度设为固定值，并在条件面板勾选恰好两个组分作为扫描轴.",
    ),
    (
        "Number of degrees of freedom is not zero",
        "自由度为不为零，条件组合在热力学上无法唯一确定体系状态。",
        "常见原因是同时给了两个组分扫描范围却让第三组分配比越界。"
        "三元体系请只让两个组分变化，第三个组分按定值固定。",
    ),
    (
        "has no attribute 'species'",
        "绘图坐标轴参数顺序有误。pycalphad 的相图函数中，横轴必须是组分（如 X(AL)），"
        "纵轴才能是温度等外部条件。",
        "请把 X(元素) 放在横轴、T/P 放在纵轴；反之会报此错.",
    ),
    (
        "There are no phases in the Database that can be active with components",
        "所选元素组合在数据库中没有任何可用的相模型。",
        "请在周期表中换一组元素，或在相列表里放宽筛选。",
    ),
    (
        "None of the passed phases are active",
        "过滤后没有任何相处于所选组分的活跃区间内。",
        "请取消部分相的排除，或换一组元素。",
    ),
    (
        "At least one component must be specified",
        "至少需要一个组分。",
        "请先在周期表中选择元素。",
    ),
    (
        "component list contains duplicate",
        "组分列表存在重复项。",
        "请检查选中的元素是否有大写重复。",
    ),
    (
        "not defined and cannot be autodetected",
        "相图类型无法自动判定：独立组分数与外部势场数不匹配。",
        "二元图请给 1 个组分扫描 + 1 个温度/压力扫描；三元图请给 2 个组分扫描。",
    ),
    (
        "netCDF4",
        "缺少 netCDF4 依赖，无法写出 netCDF 文件。",
        "可执行 pip install netCDF4，或改用 CSV 导出。",
    ),
    (
        "No module named 'openpyxl'",
        "缺少 openpyxl 依赖，无法写出 Excel 文件。",
        "可执行 pip install openpyxl，或改用 CSV 导出。",
    ),
)


def diagnose(exc: BaseException, context: str = "") -> CalculationError:
    """把任意异常翻译成 :class:`CalculationError`。

    匹配不到规则时，退化为「计算失败 + 异常类型」，并保留原始信息以便检索日志。
    """
    text = f"{type(exc).__name__}: {exc}"
    for needle, reason, suggestion in _RULES:
        if needle in text:
            msg = reason if not context else f"{context}：{reason}"
            return CalculationError(msg, f"{suggestion} 原始信息：{text[:200]}")
    msg = f"计算失败：{context}" if context else "计算失败"
    return CalculationError(msg, text[:300])


def log_exception(exc: BaseException, context: str = "") -> None:
    """记录完整堆栈，供后续排查。"""
    logger.error(
        "计算上下文: %s\n%s", context or "<none>", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    )

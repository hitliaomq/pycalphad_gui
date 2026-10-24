"""全局常量与配色。

集中放置 GUI 需要的枚举、默认值和样式，避免魔法数字散落各模块。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Tuple

# ---------------------------------------------------------------- 元素伪组分
#: 空位（vacancy）。CEF 模型大多把它当作 endmember，缺少时该相会被判为不可激活。
VACANCY = "VA"

#: 电子气占位。TDB 中写作 ``ELEMENT /-   ELECTRON_GAS``，并在
#: ``DEFAULT_COMMAND DEF_SYS_ELEMENT VA /-`` 里与空位一起被声明为默认系统元素
#: （见 pycalphad ``io/tdb.py:807``）。它不是真实元素，不能当组分用。
ELECTRON_GAS = "/-"

#: pycalphad 的 ``Database.elements`` 里会混入这两个"非真元素"占位符
PSEUDO_ELEMENTS: Tuple[str, ...] = (VACANCY, ELECTRON_GAS)

#: 合法元素名：字母开头、只含字母数字。用它一次性排掉 ``VA`` / ``/-`` / ``AL/+``
#: 这类伪组分与电荷物种，比逐个比对黑名单更稳妥。
_ELEMENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


def is_real_element(name: str) -> bool:
    """判断某个组分名是否为真实元素。"""
    return bool(_ELEMENT_NAME_RE.match(name)) and name != VACANCY

# ---------------------------------------------------------------- 支持的状态变量
STATE_VARS = ("T", "P", "N")

# ---------------------------------------------------------------- 属性枚举
PROPERTY_CHOICES: Tuple[str, ...] = (
    "GM",   # 吉布斯自由能
    "HM",   # 焓
    "SM",   # 熵
    "CPM",  # 定压热容
    "NP",        # 相分数（Workspace.get_dict("NP(*)")）
    "XSEL",      # 相中元素含量 X(相, 元素)
    "ORDERING",  # degree of ordering（有序度，需要有有序模型的相）
    "SITEFRAC",  # site fraction（占位分数）
)

#: 属性到中文显示名的映射，用于下拉框与图例标题
PROPERTY_LABELS: dict = {
    "NP": "相分数 NP(*)",
    "XSEL": "相中元素含量 X(相, 元素)",
    "ORDERING": "Degree of ordering（有序度）",
    "SITEFRAC": "Site fraction（占位分数）",
    "GM": "Gibbs 自由能 G",
    "HM": "焓 H",
    "SM": "熵 S",
    "CPM": "定压热容 Cp",
}

#: 属性曲线的曲线来源（"平衡态"还是"逐相"，或者两者都画）
#: 键给引擎用，值给下拉框用；顺序即下拉框顺序
PROPERTY_SCOPES: Tuple[str, ...] = (
    "per_phase",   # 每个相一条曲线（用户诉求：看单个相的性能）
    "balance",     # 只画全局平衡态
    "both",        # 逐相 + 平衡态参照线
)

PROPERTY_SCOPE_LABELS: dict = {
    "per_phase": "逐相（每个相一条曲线）",
    "balance": "平衡态（仅最稳定相）",
    "both": "逐相 + 平衡态对照",
}

#: 引擎里能逐相求解的属性；其余属性（化学势、活度等）只能给平衡态
PROPERTY_PER_PHASE_KEYS: Tuple[str, ...] = ("GM", "HM", "SM", "CPM")

# ---------------------------------------------------------------- 相图类型
DIAGRAM_TYPES: Tuple[str, ...] = (
    "binary_ztpf",        # 二元等压 T-X 相图（binplot）
    "ternary_isothermal",  # 三元等温等压全截面（ternplot）
    "eqplot_binary",      # 平衡态散点/连线（equilibrium + eqplot），二元
    "eqplot_ternary",     # 平衡态散点/连线（equilibrium + eqplot），三元
)

DIAGRAM_LABELS: dict = {
    "binary_ztpf": "二元 T–X 相图 (ZPFE)",
    "ternary_isothermal": "三元等温等压截面",
    "eqplot_binary": "二元平衡态 (eqplot)",
    "eqplot_ternary": "三元平衡态 (eqplot)",
    "step": "Step 图（单轴步进）",
    "isopleth": "Isopleth（垂直截面）",
}

# ---------------------------------------------------------------- 高通量输出
HT_OUTPUTS: Tuple[str, ...] = (
    "stable_phases",
    "gm_min",
    "gm_last",
    "np_liquid",
    "n_phases",
)

HT_OUTPUT_LABELS: dict = {
    "stable_phases": "稳定相组合",
    "gm_min": "最低吉布斯自由能 (J/mol)",
    "gm_last": "末态吉布斯自由能 (J/mol)",
    "np_liquid": "LIQUID 相分数",
    "n_phases": "共存相数",
}

# ---------------------------------------------------------------- ESPEI 参数优化
#: ESPEI 的三个工作模式
ESPEI_MODES: Tuple[str, ...] = (
    "generate",   # 单步参数生成（线性回归，快）
    "mcmc",       # MCMC 拟合（慢，需要已有的参数库）
    "check",      # 只校验数据集，不跑拟合
)

ESPEI_MODE_LABELS: dict = {
    "generate": "生成参数（generate_parameters）",
    "mcmc": "MCMC 拟合（mcmc）",
    "check": "校验数据集（仅检查）",
}

#: ESPEI 参考态（决定纯物质 G 的基准）
ESPEI_REF_STATES: Tuple[str, ...] = ("SGTE91", "SR2016")

#: ESPEI 多余的吉布斯自由能模型，schema 只接受 "linear"
ESPEI_EXCESS_MODELS: Tuple[str, ...] = ("linear",)

#: ESPEI 数据集类型 → 默认权重（与 espei input-schema 的默认值保持一致）
ESPEI_DATA_WEIGHTS: Tuple[str, ...] = ("ZPF", "ACR", "HM", "SM", "CPM")

#: ESPEI MCMC 可选的先验（normal 使用相对当前参数值的 loc/scale）
ESPEI_PRIORS: Tuple[str, ...] = ("zero", "normal")

#: ESPEI 默认输出文件名。相对路径会落到工作目录，界面在载入数据库后
#: 会把它替换成"数据库所在目录 + 这个名字"（见 EspeiTab.apply_settings_defaults）
DEFAULT_OUTPUT_DB = "espei_out.tdb"

# ---------------------------------------------------------------- Scheil 凝固
#: 凝固模拟方法
SCHEIL_METHODS: Tuple[str, ...] = ("scheil", "equilibrium")

SCHEIL_METHOD_LABELS: dict = {
    "scheil": "Scheil–Gulliver（非平衡）",
    "equilibrium": "平衡凝固（Equilibrium）",
}

#: 判定时"液相"用的相名优先级。TDB 里液相不一定叫 LIQUID（例如 vzr 库的 IONIC_LIQ）
LIQUID_NAME_HINTS: Tuple[str, ...] = ("LIQUID", "Liquid", "L", "IONIC_LIQ")

# ---------------------------------------------------------------- 导出
EXPORT_IMAGE_FORMATS: Tuple[str, ...] = ("png", "svg", "pdf", "jpg")
EXPORT_DATA_FORMATS: Tuple[str, ...] = ("csv", "xlsx")

# ---------------------------------------------------------------- 默认条件
DEFAULT_T_RANGE = (300.0, 1500.0, 20.0)
DEFAULT_P = 101325.0
DEFAULT_X_RANGE = (0.0, 1.0, 0.02)

# ---------------------------------------------------------------- 线程
#: 计算线程池最大并发数。CPU 密集且受 GIL 限制，默认取 CPU 核数的一半
DEFAULT_MAX_WORKERS = 4

# ---------------------------------------------------------------- 配色
#: 相图配色（对色盲友好，避免纯红/纯绿相邻）
PHASE_COLORS: Tuple[str, ...] = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
)

#: 交互图元样式
TIELINE_COLOR = "#2ca02c"
ANNOTATION_BOX = dict(boxstyle="round,pad=0.3", fc="white", ec="#444444", alpha=0.9)

# ----------------------------------------------------------------  misc
APP_NAME = "pyCalphad GUI"
APP_VERSION = "0.1.0"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


@dataclass(frozen=True)
class Progress:
    """一次计算任务的进度快照。

    用 frozen dataclass 而非可变 dict，避免多线程下被误改。
    """
    current: int
    total: int
    message: str = ""


def phase_color(index: int) -> str:
    """按索引取相颜色，超出时循环复用。"""
    if index < 0:
        return PHASE_COLORS[0]
    return PHASE_COLORS[index % len(PHASE_COLORS)]


class DiagramKind(str, Enum):
    """相图种类，用于 Worker 与引擎的类型分派。"""

    BINARY_ZTPF = "binary_ztpf"
    TERNARY_ISOTHERMAL = "ternary_isothermal"
    EQPLOT_BINARY = "eqplot_binary"
    EQPLOT_TERNARY = "eqplot_ternary"
    PROPERTY_CURVE = "property_curve"
    PROPERTY_FIELD = "property_field"
    HT_SCAN = "ht_scan"

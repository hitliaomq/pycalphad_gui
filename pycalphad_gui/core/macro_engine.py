"""Thermo-Calc 风格宏解释器（纯 Python，不依赖 PyQt6）。

一份宏就是一份按行书写的命令脚本，语法贴着 Thermo-Calc 的宏习惯：

.. code-block:: text

    # 以 # 或 // 开头的是注释
    OPEN database/alzn_mey.tdb
    ELEMENTS AL ZN
    PHASES LIQUID FCC_A1 HCP_A3
    SWEEP ZN 0 1 0.02
    SWEEP T 300 1000 10
    FIXED P=101325
    DIAGRAM BINARY

命令大小写不敏感，参数可用单 / 双引号包住（路径里有空格时必须包）。
每个计算命令（DIAGRAM / PROPERTY / SCHEIL / ESPEI / HT）算完立刻把图、
表格和数据库交给界面，所以一份宏里可以连续出好几张图。

支持的变量写法：

.. code-block:: text

    $root = ../database
    OPEN $root/alzn_mey.tdb
    $temp = 850
    SCHEIL X(ZN)=0.3 START-T=$temp

``INCLUDE`` 可以引入其它宏文件，相对路径按当前宏所在目录解析。

设计约束
--------
* **只做编排**：计算全部转交 :mod:`core.plot_engine` / ``scheil`` /
  ``espei`` / :mod:`core.high_throughput`，宏层不重复实现热力学逻辑；
* **不碰 Qt**：结果通过 :class:`MacroCallbacks` 交给调用方，后台线程因此
  可以安全执行；
* 出错一律抛 :class:`CalculationError`，并带上行号；``BaseWorker`` 那套
  中文翻译链路可直接复用。
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .conditions import ConditionPlan
from .database_manager import LoadedDatabase, filter_phases, load_database
from .diagnostics import CalculationError, log_exception
from .exporter import export_dataframe, export_figure, export_series_csv
from .high_throughput import HTConfig, run_high_throughput
from .plot_engine import compute_diagram, compute_property_curves
from .scheil_engine import ScheilConfig, run_solidification
from ..config import DIAGRAM_TYPES, HT_OUTPUTS, SCHEIL_METHODS

#: 单条 SWEEP / PROPERTY 允许的最大采样点数（再大就不是"画图"而是批算了）
MAX_SAMPLES = 5000
#: INCLUDE 递归深度上限，防互相引用把栈打穿
MAX_INCLUDE_DEPTH = 8

#: 相图类型别名（宏里可以写 THERMO-CALC 风格的短名）
_DIAGRAM_ALIASES: Dict[str, str] = {
    "BINARY": "binary_ztpf",
    "ZTFF": "binary_ztpf",
    "BIN": "binary_ztpf",
    "TERNARY": "ternary_isothermal",
    "ISOTHERMAL": "ternary_isothermal",
    "TERN": "ternary_isothermal",
    "EQPLOT-BINARY": "eqplot_binary",
    "EQ-BINARY": "eqplot_binary",
    "EQPLOT-TERNARY": "eqplot_ternary",
    "EQ-TERNARY": "eqplot_ternary",
    "STEP": "step",
    "ISOPLETH": "isopleth",
}

#: 命令别名
_COMMAND_ALIASES: Dict[str, str] = {
    "LOAD": "OPEN",
    "LOAD-DATABASE": "OPEN",
    "OPEN-DATABASE": "OPEN",
    "DATABASE": "OPEN",
    "TDB": "OPEN",
    "COMPONENTS": "ELEMENTS",
    "SELECT-ELEMENTS": "ELEMENTS",
    "SELECT-COMPONENTS": "ELEMENTS",
    "PHASE": "PHASES",
    "EXCLUDE-PHASES": "EXCLUDE",
    "REJECT-PHASES": "EXCLUDE",
    "REJECT": "EXCLUDE",
    "CONDITIONS": "SWEEP",
    "COND": "SWEEP",
    "TEMPERATURE": "FIXED",
    "OPTION": "OPTIONS",
    "PLOT-OPTIONS": "OPTIONS",
    "SOLIDIFY": "SCHEIL",
    "EQ-SOLIDIFY": "EQUILIBRIUM",
    "SAVE": "EXPORT",
    "WRITE": "EXPORT",
    "ECHO": "PRINT",
    "SHOW-STATUS": "SHOW",
    "STATUS": "SHOW",
}

_DEFAULT_OPTIONS: Dict[str, Any] = {
    "tielines": True,
    "label_nodes": False,
    "grid_fill": False,
    "auto_start": False,
}

#: 允许在 FIXED 里出现的状态变量
_STATE_KEYS = {"T", "P", "N"}

#: 可以出现在宏里的真 / 假写法
_TRUE = {"ON", "TRUE", "YES", "Y", "1"}
_FALSE = {"OFF", "FALSE", "NO", "N", "0"}

_TOKEN_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')
_ASSIGN_RE = re.compile(r"^\$([A-Za-z_]\w*)\s*=\s*(.*)$")
_OPTION_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_\-().,/]*)=(.*)$")
_VAR_RE = re.compile(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)")
_X_RE = re.compile(r"^X\(\s*([^,]+?)\s*,\s*([^)]+?)\s*\)$")
_X1_RE = re.compile(r"^X\(\s*([^,()]+?)\s*\)$")
_ORDER_RE = re.compile(r"^(?:DEGREE-OF-ORDERING|DEGREE_OF_ORDERING)\(\s*([^)]+?)\s*\)$")
_SITEFRAC_RE = re.compile(r"^(?:SITEFRACTION|SITE_FRACTION|SITEFRAC)\(\s*([^)]+?)\s*\)$")


class MacroCancelled(Exception):
    """宏被用户取消（内部信号，不面向用户）。"""


# ---------------------------------------------------------------- 回调
class MacroCallbacks:
    """宏执行过程中向宿主（UI / 测试）汇报的出口。

    所有回调都可缺省；后台线程只调用它们，不直接操作 Qt 控件——UI 侧把
    这些方法接到信号上即可实现跨线程排队。
    """

    def __init__(
        self,
        log: Optional[Callable[[str], None]] = None,
        status: Optional[Callable[[str], None]] = None,
        progress: Optional[Callable[[int, int, str], None]] = None,
        figure: Optional[Callable[[Any, Any, str], None]] = None,
        database: Optional[Callable[[str], None]] = None,
        selection: Optional[Callable[[List[str], List[str]], None]] = None,
        table: Optional[Callable[[Any, str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._log = log
        self._status = status
        self._progress = progress
        self._figure = figure
        self._database = database
        self._selection = selection
        self._table = table
        self._should_cancel = should_cancel

    # -- 安全调用：回调异常绝不能打断计算 -------------------------------
    def log(self, text: str) -> None:
        if self._log is not None:
            try:
                self._log(text)
            except Exception:  # noqa: BLE001
                pass

    def status(self, text: str) -> None:
        if self._status is not None:
            try:
                self._status(text)
            except Exception:  # noqa: BLE001
                pass

    def progress(self, current: int, total: int, text: str = "") -> None:
        if self._progress is not None:
            try:
                self._progress(int(current), max(1, int(total)), text)
            except Exception:  # noqa: BLE001
                pass

    def show_figure(self, figure: Any, axes: Any, caption: str) -> None:
        if self._figure is not None:
            try:
                self._figure(figure, axes, caption)
            except Exception:  # noqa: BLE001
                pass

    def update_database(self, path: Path) -> None:
        if self._database is not None:
            try:
                self._database(str(path))
            except Exception:  # noqa: BLE001
                pass

    def update_selection(self, elements: Sequence[str], phases: Sequence[str]) -> None:
        if self._selection is not None:
            try:
                self._selection(list(elements), list(phases))
            except Exception:  # noqa: BLE001
                pass

    def show_table(self, frame: Any, title: str) -> None:
        if self._table is not None:
            try:
                self._table(frame, title)
            except Exception:  # noqa: BLE001
                pass

    def is_cancelled(self) -> bool:
        if self._should_cancel is None:
            return False
        try:
            return bool(self._should_cancel())
        except Exception:  # noqa: BLE001
            return False


# ---------------------------------------------------------------- 结果
@dataclass
class MacroResult:
    """一次宏运行的汇总（日志由回调逐行送出）。"""

    elapsed_s: float = 0.0
    n_commands: int = 0
    n_results: int = 0
    outputs: List[Path] = field(default_factory=list)
    database_path: Optional[Path] = None
    cancelled: bool = False


# ---------------------------------------------------------------- 执行状态
@dataclass
class _State:
    database: Optional[LoadedDatabase] = None
    elements: List[str] = field(default_factory=list)
    phases: List[str] = field(default_factory=list)
    sweeps: Dict[str, Tuple[float, float, float]] = field(default_factory=dict)
    fixed: Dict[str, float] = field(default_factory=dict)
    diagram_type: str = "binary_ztpf"
    options: Dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_OPTIONS))
    variables: Dict[str, str] = field(default_factory=dict)
    #: 最近一次结果，供 EXPORT 使用
    last_figure: Any = None
    last_axes: Any = None
    last_caption: str = ""
    last_frame: Any = None
    last_series: List[Tuple[str, np.ndarray, np.ndarray]] = field(default_factory=list)
    last_x_label: str = "x"
    last_y_label: str = "y"

    def reset_conditions(self) -> None:
        self.sweeps.clear()
        self.fixed.clear()
        self.options = dict(_DEFAULT_OPTIONS)
        self.diagram_type = "binary_ztpf"


# ---------------------------------------------------------------- 入口
def _initial_state(
    initial_database: Optional[str],
    initial_elements: Optional[Sequence[str]],
    initial_phases: Optional[Sequence[str]],
) -> _State:
    """用界面当前状态建一个宏执行状态（载不进来就留空）。"""
    state = _State()
    if not initial_database:
        return state
    path = Path(initial_database)
    if not path.is_file():
        return state
    try:
        state.database = load_database(path)
        state.phases = state.database.phase_names
        elements = list(initial_elements or [])
        if elements:
            # 宽松解析：界面里可能残留库外符号，不能因为一个坏符号
            # 就把已经可用的初始数据库整个丢掉
            resolved = [state.database.resolve(e) for e in elements]
            state.elements = [r for r in resolved if r is not None and r != "VA"]
        elif len(state.database.display_elements) == 2:
            state.elements = list(state.database.display_elements)
        if initial_phases:
            kept = [p for p in initial_phases if p in state.database.phases]
            if kept:
                state.phases = sorted(kept)
    except CalculationError:
        # 初始库只是便利，载不进来不影响宏里自己 OPEN
        state.database = None
    return state


def run_macro_text(
    text: str,
    base_dir: Optional[Path] = None,
    callbacks: Optional[MacroCallbacks] = None,
    initial_database: Optional[str] = None,
    initial_elements: Optional[Sequence[str]] = None,
    initial_phases: Optional[Sequence[str]] = None,
) -> MacroResult:
    """执行一段宏文本。

    Parameters
    ----------
    text
        宏内容。
    base_dir
        相对路径的基准目录（通常是被打开宏文件所在目录）。
    callbacks
        日志 / 图 / 数据库等回调。
    initial_database / initial_elements / initial_phases
        界面当前状态。宏里可以不写 ``OPEN``，直接沿用界面里已载入的库。
    """
    cb = callbacks or MacroCallbacks()
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    state = _initial_state(initial_database, initial_elements, initial_phases)

    t0 = time.perf_counter()
    result = _Runner(cb, start_dir=root)
    try:
        result.execute_text(text, state, root, depth=0)
    except MacroCancelled:
        result.summary.cancelled = True
        cb.log("已取消：宏在检查点停止。")
        cb.status("已取消")
    result.summary.elapsed_s = time.perf_counter() - t0
    result.summary.database_path = state.database.path if state.database else None
    return result.summary


class MacroSession:
    """交互式宏会话：状态跨命令保留，每次执行一行。

    交互式命令面板每敲一条命令就走一次 :meth:`run_line`；数据库、元素、相、
    扫描 / 固定条件、变量和最近一次结果都留在 ``_State`` 里，所以
    ``OPEN`` → ``ELEMENTS`` → ``SWEEP`` → ``DIAGRAM`` 可以分四次输入。
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        callbacks: Optional[MacroCallbacks] = None,
        initial_database: Optional[str] = None,
        initial_elements: Optional[Sequence[str]] = None,
        initial_phases: Optional[Sequence[str]] = None,
    ) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self.callbacks = callbacks or MacroCallbacks()
        self._initial = (
            initial_database,
            list(initial_elements or []),
            list(initial_phases or []),
        )
        self._state: Optional[_State] = None
        self._runner: Optional[_Runner] = None
        #: 整个会话的累计结果
        self.total = MacroResult()

    # ------------------------------------------------------------ 状态
    @property
    def started(self) -> bool:
        """是否已经执行过至少一条命令（初始数据库此时才载入）。"""
        return self._runner is not None

    @property
    def database(self) -> Optional[LoadedDatabase]:
        return self._state.database if self._state is not None else None

    @property
    def elements(self) -> List[str]:
        return list(self._state.elements) if self._state is not None else []

    @property
    def phases(self) -> List[str]:
        return list(self._state.phases) if self._state is not None else []

    @property
    def variables(self) -> Dict[str, str]:
        return dict(self._state.variables) if self._state is not None else {}

    def set_callbacks(self, callbacks: MacroCallbacks) -> None:
        """替换汇报出口（每步 worker 都带着自己的信号回调进来）。"""
        self.callbacks = callbacks
        if self._runner is not None:
            self._runner.cb = callbacks

    def set_base_dir(self, path: Path | str) -> None:
        """切换相对路径基准（打开 / 另存宏文件后调用）。"""
        self.base_dir = Path(path)
        if self._runner is not None:
            self._runner.base_dir = self.base_dir

    def reset(self) -> None:
        """丢弃全部会话状态；下一条命令重新从界面上下文开始。"""
        self._state = None
        self._runner = None
        self.total = MacroResult()

    # ------------------------------------------------------------ 执行
    def _ensure_started(self) -> _Runner:
        if self._runner is not None:
            return self._runner
        database, elements, phases = self._initial
        self._state = _initial_state(database, elements, phases)
        self._runner = _Runner(self.callbacks, start_dir=self.base_dir, echo=False)
        return self._runner

    def run_line(self, text: str) -> MacroResult:
        """执行一条命令，返回这一步的增量结果（累计量记在 ``total``）。"""
        runner = self._ensure_started()
        line = _strip_comment(text).strip()
        step = MacroResult()
        if not line:
            return step
        before_commands = runner.summary.n_commands
        before_results = runner.summary.n_results
        before_outputs = len(runner.summary.outputs)
        t0 = time.perf_counter()
        try:
            runner.execute_text(line, self._state, self.base_dir, depth=0,
                                numbered=False)
        except MacroCancelled:
            step.cancelled = True
            self.callbacks.log("已取消：宏在检查点停止。")
            self.callbacks.status("已取消")
        step.elapsed_s = time.perf_counter() - t0
        step.n_commands = runner.summary.n_commands - before_commands
        step.n_results = runner.summary.n_results - before_results
        step.outputs = list(runner.summary.outputs[before_outputs:])
        step.database_path = self._state.database.path if self._state.database else None
        self.total.elapsed_s += step.elapsed_s
        self.total.n_commands += step.n_commands
        self.total.n_results += step.n_results
        self.total.outputs.extend(step.outputs)
        self.total.database_path = step.database_path
        return step


def run_macro_file(
    path: str | Path,
    callbacks: Optional[MacroCallbacks] = None,
    initial_database: Optional[str] = None,
    initial_elements: Optional[Sequence[str]] = None,
    initial_phases: Optional[Sequence[str]] = None,
) -> MacroResult:
    """读取并执行一个宏文件（相对路径按文件所在目录解析）。"""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise CalculationError(f"无法读取宏文件：{file_path.name}", str(exc)) from exc
    return run_macro_text(
        text,
        base_dir=file_path.parent,
        callbacks=callbacks,
        initial_database=initial_database,
        initial_elements=initial_elements,
        initial_phases=initial_phases,
    )


# ---------------------------------------------------------------- 解析工具
def _strip_comment(line: str) -> str:
    """去掉行内注释；引号里的 ``#`` / ``//`` 不算注释。"""
    quote = ""
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#":
            return line[:i]
        elif ch == "/" and line[i : i + 2] == "//":
            return line[:i]
        i += 1
    return line


def _tokenize(line: str) -> List[Tuple[str, bool]]:
    """切词，并标记该词是否整段被引号包住（引号内的 ``=`` 不是选项）。"""
    out: List[Tuple[str, bool]] = []
    for match in _TOKEN_RE.finditer(line):
        quoted = match.group(3) is None
        text = (match.group(1) if match.group(1) is not None
                else match.group(2) if match.group(2) is not None
                else match.group(3) or "")
        if text != "":
            out.append((text, quoted))
    return out


def _substitute(token: str, variables: Mapping[str, str], lineno: int) -> str:
    def _repl(match: re.Match) -> str:
        name = match.group(1) or match.group(2)
        if name not in variables:
            raise CalculationError(
                f"第 {lineno} 行：变量 ${name} 没有定义",
                "先用 SET 或 $name = 值 定义它",
            )
        return variables[name]

    return _VAR_RE.sub(_repl, token)


def _bool(value: str, where: str) -> bool:
    up = value.strip().upper()
    if up in _TRUE:
        return True
    if up in _FALSE:
        return False
    raise CalculationError(f"{where} 需要 ON / OFF，收到 {value!r}", "例如 TIELINES=OFF")


def _number(value: str, where: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CalculationError(f"{where} 需要一个数字，收到 {value!r}", "例如 300 / 0.02 / 1e-4") from exc
    if not math.isfinite(out):
        raise CalculationError(f"{where} 不能是 {value}", "请输入有限数值")
    return out


def _samples(start: float, stop: float, step: float, where: str) -> List[float]:
    """把 (起, 止, 步) 展开成采样点，方向由步长符号决定。"""
    if step == 0:
        raise CalculationError(f"{where} 的步长不能为 0", "例如 STEP 10")
    if start == stop:
        raise CalculationError(f"{where} 的起点和终点不能相同", "至少给出两个不同的点")
    span = abs((stop - start) / step)
    n = int(round(span))
    if n < 1:
        n = 1
    if n + 1 > MAX_SAMPLES:
        raise CalculationError(
            f"{where} 有 {n + 1} 个采样点，超过上限 {MAX_SAMPLES}",
            "请放大步长或缩小区间；一次算这么多点会等很久",
        )
    return [round(start + (stop - start) * i / n, 10) for i in range(n + 1)]


def _resolve_input(path_text: str, base_dir: Path) -> Path:
    """输入文件：依次尝试宏目录、上两级目录、当前工作目录。"""
    raw = Path(path_text).expanduser()
    if raw.is_absolute():
        return raw
    candidates = [
        base_dir / raw,
        base_dir.parent / raw,
        base_dir.parent.parent / raw,
        Path.cwd() / raw,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0]


def _resolve_output(path_text: str, base_dir: Path) -> Path:
    """输出文件：相对宏目录，父目录自动建好。"""
    raw = Path(path_text).expanduser()
    target = raw if raw.is_absolute() else (base_dir / raw)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CalculationError(f"无法创建输出目录：{target.parent}", str(exc)) from exc
    return target.resolve()


def _resolve_phase(database: LoadedDatabase, name: str) -> str:
    up = name.strip().upper()
    for phase in database.phases:
        if phase.upper() == up:
            return phase
    raise CalculationError(
        f"数据库 {database.name} 中没有相 {name}",
        f"可选相：{', '.join(database.phase_names[:20])}"
        + ("…" if len(database.phase_names) > 20 else ""),
    )


# ---------------------------------------------------------------- 执行器
class _Runner:
    """逐行执行宏；维护汇总信息，命令实现按职责拆成 ``_cmd_*``。"""

    def __init__(self, callbacks: MacroCallbacks, start_dir: Path,
                 echo: bool = True) -> None:
        self.cb = callbacks
        self.base_dir = start_dir
        #: 是否把命令行原文回显到日志（交互式会话自己回显，无需重复）
        self.echo = echo
        self.summary = MacroResult()
        #: 当前嵌套执行链的深度（栈顶即当前文件），供 INCLUDE 判断递归
        self._depth_stack: List[int] = []

    # ------------------------------------------------------------ 主循环
    def execute_text(self, text: str, state: _State, base_dir: Path, depth: int,
                     numbered: bool = True) -> None:
        if depth > MAX_INCLUDE_DEPTH:
            raise CalculationError(
                "INCLUDE 嵌套层数过多",
                f"最多 {MAX_INCLUDE_DEPTH} 层，请检查宏之间是否互相引用",
            )
        self._depth_stack.append(depth)
        try:
            lines = text.splitlines()
            logical: List[Tuple[int, str]] = []
            pending = ""
            pending_line = 0
            for index, raw in enumerate(lines, start=1):
                line = raw.rstrip()
                if pending:
                    line = pending + " " + line.strip()
                    index = pending_line
                    pending = ""
                if line.endswith("\\"):
                    pending = line[:-1]
                    pending_line = index
                    continue
                stripped = _strip_comment(line).strip()
                if stripped:
                    logical.append((index, stripped))
            if pending:
                raise CalculationError(
                    f"第 {pending_line} 行：续行符后面没有内容",
                    "删除行尾的 \\ 或补上下一行",
                )

            for offset, (lineno, line) in enumerate(logical):
                if self.cb.is_cancelled():
                    raise MacroCancelled()
                self.cb.progress(offset + 1, max(1, len(logical)),
                                 f"第 {lineno} 行 / {len(logical)}")
                try:
                    self._execute_line(lineno, line, state, base_dir)
                except MacroCancelled:
                    raise
                except CalculationError as exc:
                    if not numbered:
                        raise
                    raise CalculationError(
                        f"第 {lineno} 行：{exc.user_message}", exc.detail
                    ) from exc
                except Exception as exc:  # noqa: BLE001 - 边界处统一翻译
                    log_exception(exc, f"宏第 {lineno} 行")
                    from .diagnostics import diagnose

                    translated = diagnose(exc, "宏")
                    if not numbered:
                        raise CalculationError(
                            translated.user_message, translated.detail
                        ) from exc
                    raise CalculationError(
                        f"第 {lineno} 行：{translated.user_message}", translated.detail
                    ) from exc
                self.summary.n_commands += 1
        finally:
            self._depth_stack.pop()

    def _execute_line(self, lineno: int, line: str, state: _State, base_dir: Path) -> None:
        assign = _ASSIGN_RE.match(line)
        if assign:
            name, value = assign.group(1), assign.group(2).strip()
            value = _substitute(value, state.variables, lineno)
            # 整段被引号包住时去掉引号，方便 SET 里写带空格的路径
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            state.variables[name] = value
            self.cb.log(f"$ {name} = {value}")
            return

        tokens = [
            (_substitute(text, state.variables, lineno), quoted)
            for text, quoted in _tokenize(line)
        ]
        if not tokens:
            return
        command = tokens[0][0].upper()
        command = _COMMAND_ALIASES.get(command, command)
        args: List[str] = []
        opts: Dict[str, str] = {}
        for token, quoted in tokens[1:]:
            match = None if quoted else _OPTION_RE.match(token)
            if match is not None and not token.upper().startswith("HTTP"):
                opts[match.group(1).upper()] = match.group(2)
            else:
                args.append(token)

        if self.echo:
            self.cb.log(f"[{lineno}] {line}")
        if command in _DIAGRAM_ALIASES:
            self._cmd_diagram(state, [command] + args, opts)
            return
        handler = getattr(self, f"_cmd_{command.lower().replace('-', '_')}", None)
        if handler is None:
            raise CalculationError(
                f"未知的宏命令：{tokens[0][0]}",
                "可用命令：OPEN / ELEMENTS / PHASES / EXCLUDE / SWEEP / FIXED / "
                "DIAGRAM / OPTIONS / PROPERTY / SCHEIL / EQUILIBRIUM / ESPEI / "
                "HT / EXPORT / PRINT / SET / INCLUDE / RESET / SHOW",
            )
        handler(state, args, opts, base_dir)

    # ------------------------------------------------------------ 公共检查
    def _db(self, state: _State) -> LoadedDatabase:
        if state.database is None:
            raise CalculationError(
                "宏还没有载入数据库",
                "先写一行 OPEN 数据库路径，或在界面里打开一个 TDB / DAT",
            )
        return state.database

    def _components(self, state: _State) -> List[str]:
        database = self._db(state)
        if not state.elements:
            raise CalculationError(
                "还没有选择元素",
                "先写一行 ELEMENTS 元素1 元素2（多元素库可写 ELEMENTS *）",
            )
        return database.components_for(state.elements)

    def _phases(self, state: _State) -> List[str]:
        database = self._db(state)
        return filter_phases(database, state.phases)

    def _announce(self, text: str) -> None:
        self.cb.log(text)
        self.cb.status(text)

    def _progress_cb(self):
        def _cb(cur: int, total: int, msg: str = "") -> None:
            self.cb.progress(cur, total, msg)

        return _cb

    # ------------------------------------------------------------ 数据源
    def _cmd_open(self, state: _State, args: List[str], opts: Dict[str, str],
                  base_dir: Path) -> None:
        if not args:
            raise CalculationError("OPEN 需要一个数据库文件路径", "例如 OPEN database/alzn_mey.tdb")
        path = _resolve_input(args[0], base_dir)
        if not path.is_file():
            raise CalculationError(f"找不到数据库文件：{args[0]}", f"解析后路径：{path}")
        database = load_database(path)
        state.database = database
        state.phases = database.phase_names
        state.reset_conditions()
        if len(database.display_elements) == 2:
            state.elements = list(database.display_elements)
        else:
            state.elements = []
        for warning in database.warnings:
            self.cb.log(f"! {warning}")
        self.cb.update_database(database.path)
        self.cb.update_selection(state.elements, state.phases)
        self._announce(
            f"已载入 {database.name}｜元素数 {len(database.display_elements)}｜"
            f"相数 {len(database.phases)}"
        )
        if not state.elements:
            self.cb.log(
                "! 该库元素较多，请用 ELEMENTS 明确选择元素（也可写 ELEMENTS * 全选）"
            )

    def _cmd_elements(self, state: _State, args: List[str], opts: Dict[str, str],
                      base_dir: Path) -> None:
        database = self._db(state)
        if not args:
            raise CalculationError("ELEMENTS 需要至少一个元素符号", "例如 ELEMENTS AL ZN")
        symbols = [a.strip().rstrip(",;") for a in args if a.strip()]
        if any(s.upper() in ("*", "ALL") for s in symbols):
            resolved = list(database.display_elements)
        else:
            resolved = database.normalize_all(symbols)
        if not any(database.resolve(e) != "VA" for e in resolved):
            raise CalculationError(
                "至少选择一个真实元素（VA 只是空位）",
                f"可选元素：{', '.join(database.display_elements)}",
            )
        state.elements = [e for e in resolved if e != "VA"]
        self.cb.update_selection(state.elements, state.phases)
        self._announce(f"元素：{' + '.join(state.elements)}")

    def _cmd_phases(self, state: _State, args: List[str], opts: Dict[str, str],
                    base_dir: Path) -> None:
        database = self._db(state)
        if not args:
            raise CalculationError("PHASES 需要至少一个相名", "例如 PHASES LIQUID FCC_A1")
        if any(a.upper() in ("*", "ALL") for a in args):
            state.phases = database.phase_names
        else:
            names: List[str] = []
            remove: List[str] = []
            for token in args:
                if token.startswith("+"):
                    names.append(_resolve_phase(database, token[1:]))
                elif token.startswith("-"):
                    remove.append(_resolve_phase(database, token[1:]))
                else:
                    names.append(_resolve_phase(database, token))
            if remove:
                base = names or list(state.phases)
                state.phases = [p for p in base if p not in remove]
            else:
                state.phases = names
        state.phases = filter_phases(database, state.phases)
        self.cb.update_selection(state.elements, state.phases)
        self._announce(f"相：{', '.join(state.phases)}")

    def _cmd_exclude(self, state: _State, args: List[str], opts: Dict[str, str],
                     base_dir: Path) -> None:
        database = self._db(state)
        if not args:
            raise CalculationError("EXCLUDE 需要至少一个相名", "例如 EXCLUDE BCC_A2")
        remove = {_resolve_phase(database, a) for a in args}
        kept = [p for p in state.phases if p not in remove]
        state.phases = filter_phases(database, kept)
        self.cb.update_selection(state.elements, state.phases)
        self._announce(f"排除后保留 {len(state.phases)} 个相")

    def _cmd_sweep(self, state: _State, args: List[str], opts: Dict[str, str],
                   base_dir: Path) -> None:
        database = self._db(state)
        words = [a for a in args if a.upper() not in ("FROM", "TO", "STEP", "START", "STOP", "END")]
        if len(words) < 4:
            raise CalculationError(
                "SWEEP 需要：目标 起点 终点 步长",
                "例如 SWEEP T 300 1000 10 或 SWEEP ZN 0 1 0.02",
            )
        target = words[0].strip().upper()
        if target not in _STATE_KEYS:
            target = (database.resolve(target) or target).upper()
            if database.resolve(target) is None:
                raise CalculationError(
                    f"扫描目标 {words[0]} 不在数据库 {database.name} 中",
                    f"可选元素：{', '.join(database.display_elements)}；也可扫 T / P",
                )
        start = _number(words[1], f"SWEEP {target} 起点")
        stop = _number(words[2], f"SWEEP {target} 终点")
        step = _number(words[3], f"SWEEP {target} 步长")
        _samples(start, stop, step, f"SWEEP {target}")
        state.sweeps[target] = (start, stop, step)
        self._announce(f"扫描 {target}：{start:g} → {stop:g}，步长 {step:g}")

    def _cmd_fixed(self, state: _State, args: List[str], opts: Dict[str, str],
                   base_dir: Path) -> None:
        database = self._db(state)
        pairs: List[Tuple[str, str]] = list(opts.items())
        for i in range(0, len(args) - 1, 2):
            pairs.append((args[i].upper(), args[i + 1]))
        if not pairs:
            raise CalculationError("FIXED 需要 变量=数值", "例如 FIXED T=600 或 FIXED X(ZN)=0.3")
        for key, value in pairs:
            key = key.strip()
            up = key.upper()
            if up in _STATE_KEYS:
                state.fixed[up] = _number(value, f"FIXED {up}")
                continue
            match = _X1_RE.match(key)
            elem = match.group(1).strip() if match else key
            resolved = database.resolve(elem)
            if resolved is None:
                raise CalculationError(
                    f"固定成分 {elem} 不在数据库 {database.name} 中",
                    f"可选元素：{', '.join(database.display_elements)}",
                )
            state.fixed[resolved.upper()] = _number(value, f"FIXED {key}")
        self._announce(
            "固定条件：" + "，".join(f"{k}={v:g}" for k, v in state.fixed.items())
        )

    # ------------------------------------------------------------ 绘图选项
    def _apply_plot_options(self, state: _State, opts: Mapping[str, str]) -> None:
        for key, value in opts.items():
            up = key.upper()
            if up in ("TIELINES", "TIE-LINES", "TIE"):
                state.options["tielines"] = _bool(value, key)
            elif up in ("LABELS", "LABEL-NODES", "NODES"):
                state.options["label_nodes"] = _bool(value, key)
            elif up in ("GRID", "GRID-FILL", "FILL", "SHADED"):
                state.options["grid_fill"] = _bool(value, key)
            elif up in ("AUTO-START", "AUTOSTART"):
                state.options["auto_start"] = _bool(value, key)
            elif up == "STEP-Y":
                state.options["step_y"] = self._parse_step_y(value)
            elif up == "FIG-SIZE":
                parts = [p for p in re.split(r"[,xX]", value) if p.strip()]
                if len(parts) != 2:
                    raise CalculationError("FIG-SIZE 需要 宽,高", "例如 FIG-SIZE=9,6")
                state.options["figsize"] = (float(parts[0]), float(parts[1]))
            else:
                raise CalculationError(
                    f"未知绘图选项：{key}",
                    "可用：TIELINES / LABELS / GRID / AUTO-START / STEP-Y / FIG-SIZE",
                )

    def _parse_step_y(self, value: str) -> Any:
        raw = value.strip()
        up = raw.upper()
        if up in ("NP", "FRACTION", "PHASE-FRACTION"):
            return None  # 引擎默认就是相分数
        match = _X1_RE.match(raw)
        if match:
            return ("x", match.group(1).strip().upper())
        return ("prop", raw)

    def _cmd_options(self, state: _State, args: List[str], opts: Dict[str, str],
                     base_dir: Path) -> None:
        if not opts:
            raise CalculationError(
                "OPTIONS 需要至少一个 键=值", "例如 OPTIONS TIELINES=OFF GRID=ON"
            )
        self._apply_plot_options(state, opts)
        self._announce(f"绘图选项：{'，'.join(f'{k}={v}' for k, v in opts.items())}")

    # ------------------------------------------------------------ 相图
    def _cmd_diagram(self, state: _State, args: List[str], opts: Dict[str, str],
                     base_dir: Path) -> None:
        database = self._db(state)
        comps = self._components(state)
        if not args:
            raise CalculationError(
                "DIAGRAM 需要相图类型",
                "BINARY / TERNARY / EQPLOT-BINARY / EQPLOT-TERNARY / STEP / ISOPLETH",
            )
        raw = args[0].strip().upper()
        kind = _DIAGRAM_ALIASES.get(raw, raw.lower())
        if kind not in DIAGRAM_TYPES and kind not in ("step", "isopleth"):
            raise CalculationError(
                f"未知相图类型：{args[0]}",
                "可用：BINARY / TERNARY / EQPLOT-BINARY / EQPLOT-TERNARY / STEP / ISOPLETH",
            )
        state.diagram_type = kind
        if opts:
            self._apply_plot_options(state, opts)
        phases = self._phases(state)
        plan = ConditionPlan.from_ui(database, kind, state.sweeps, state.fixed)
        options = dict(state.options)
        if options.get("step_y") is None:
            options.pop("step_y", None)

        self.cb.progress(0, 1, f"正在计算相图（{kind}）…")
        result = compute_diagram(
            database, comps, phases, plan, options,
            figure=None, progress=self._progress_cb(),
        )
        state.last_figure = result.figure
        state.last_axes = result.axes
        state.last_caption = f"{result.title}｜{result.condition_text}"
        state.last_frame = None
        state.last_series = []
        self.cb.show_figure(result.figure, [result.axes], state.last_caption)
        self.summary.n_results += 1
        self._announce(
            f"相图完成：{result.title}｜{result.condition_text}｜"
            f"耗时 {result.elapsed_s:.1f} s"
        )

    # ------------------------------------------------------------ 属性
    def _cmd_property(self, state: _State, args: List[str], opts: Dict[str, str],
                      base_dir: Path) -> None:
        database = self._db(state)
        comps = self._components(state)
        words = [a for a in args if a.upper() not in ("VS.", "VS", "FROM", "TO", "STEP")]
        if len(words) < 5:
            raise CalculationError(
                "PROPERTY 需要：属性 扫描轴 起点 终点 步长",
                "例如 PROPERTY GM VS ZN FROM 0 TO 1 STEP 0.02 T=600",
            )
        target = self._property_target(database, words[0])
        axis_raw = words[1].strip()
        axis_up = axis_raw.upper()
        if axis_up in _STATE_KEYS:
            axis = axis_up
        else:
            resolved = database.resolve(axis_raw)
            if resolved is None:
                raise CalculationError(
                    f"扫描轴 {axis_raw} 不在数据库 {database.name} 中",
                    f"可选元素：{', '.join(database.display_elements)}；也可扫 T",
                )
            axis = resolved.upper()
        start = _number(words[2], "PROPERTY 起点")
        stop = _number(words[3], "PROPERTY 终点")
        step = _number(words[4], "PROPERTY 步长")
        values = _samples(start, stop, step, "PROPERTY")

        scope = opts.get("SCOPE", "balance").strip().lower().replace("_", "-")
        scope = {"per-phase": "per_phase", "balance": "balance", "both": "both"}.get(
            scope, scope
        )
        if scope not in ("per_phase", "balance", "both"):
            raise CalculationError(
                f"未知曲线来源：{opts.get('SCOPE')}",
                "SCOPE=per_phase / balance / both",
            )
        options: Dict[str, Any] = {
            "fixed_t": _number(opts.get("T", "600"), "PROPERTY T"),
            "fixed_x": _number(opts.get("X", "0.5"), "PROPERTY X"),
            "curve_scope": scope,
        }
        # 三元及以上扫温度时必须把所有剩余组分钉住；X(元素)=分数 就是为此准备的
        fixed_comps: Dict[str, float] = {}
        for key, value in opts.items():
            match = _X1_RE.match(key)
            if not match:
                continue
            elem = database.resolve(match.group(1).strip())
            if elem is None:
                raise CalculationError(
                    f"固定成分 {match.group(1)} 不在数据库 {database.name} 中",
                    f"可选元素：{', '.join(database.display_elements)}",
                )
            fixed_comps[elem.upper()] = _number(value, f"PROPERTY {key}")
        if fixed_comps:
            options["fixed_comps"] = fixed_comps
        if "PER-PHASE" in opts or "PER_PHASE" in opts:
            requested = [
                _resolve_phase(database, p.strip())
                for p in re.split(r"[,;]", opts.get("PER-PHASE") or opts.get("PER_PHASE"))
                if p.strip()
            ]
            allowed = set(self._phases(state))
            options["per_phase_phases"] = [p for p in requested if p in allowed]
        phases = self._phases(state)

        self.cb.progress(0, 1, f"正在计算属性 {target} …")
        result = compute_property_curves(
            database, comps, phases, target, axis, values,
            options=options, figure=None, progress=self._progress_cb(),
        )
        state.last_figure = result.figure
        state.last_axes = result.axes
        state.last_caption = f"{result.title}｜{result.condition_text}"
        state.last_series = [
            (name, np.asarray(xs), np.asarray(ys))
            for name, (xs, ys) in result.series.items()
        ]
        state.last_x_label = result.x_label
        state.last_y_label = result.y_label
        state.last_frame = None
        self.cb.show_figure(result.figure, [result.axes], state.last_caption)
        self.summary.n_results += 1
        self._announce(
            f"属性完成：{target} — {result.title}｜{result.condition_text}｜"
            f"耗时 {result.elapsed_s:.1f} s"
        )

    def _property_target(self, database: LoadedDatabase, raw: str) -> str:
        text = raw.strip()
        up = text.upper()
        simple = {"G": "GM", "H": "HM", "S": "SM", "CP": "CPM", "C_P": "CPM"}
        if up in simple:
            return simple[up]
        if up in ("GM", "HM", "SM", "CPM", "NP"):
            return up
        match = _X_RE.match(text)
        if match:
            phase = _resolve_phase(database, match.group(1))
            elem = database.resolve(match.group(2).strip())
            if elem is None:
                raise CalculationError(
                    f"元素 {match.group(2)} 不在数据库 {database.name} 中",
                    f"可选元素：{', '.join(database.display_elements)}",
                )
            return f"X({phase},{elem.upper()})"
        match = _ORDER_RE.match(text)
        if match:
            return f"degree_of_ordering({_resolve_phase(database, match.group(1))})"
        match = _SITEFRAC_RE.match(text)
        if match:
            return f"sitefraction({_resolve_phase(database, match.group(1))})"
        return text

    # ------------------------------------------------------------ 凝固
    def _cmd_scheil(self, state: _State, args: List[str], opts: Dict[str, str],
                    base_dir: Path) -> None:
        self._solidification(state, opts, method="scheil", args=args)

    def _cmd_equilibrium(self, state: _State, args: List[str], opts: Dict[str, str],
                         base_dir: Path) -> None:
        self._solidification(state, opts, method="equilibrium", args=args)

    def _solidification(self, state: _State, opts: Dict[str, str], method: str,
                        args: Sequence[str]) -> None:
        database = self._db(state)
        comps = self._components(state)
        phases = self._phases(state)

        composition: Dict[str, float] = {}
        for key, value in opts.items():
            match = _X1_RE.match(key)
            if match:
                elem = database.resolve(match.group(1).strip())
                if elem is None:
                    raise CalculationError(
                        f"成分元素 {match.group(1)} 不在数据库 {database.name} 中",
                        f"可选元素：{', '.join(database.display_elements)}",
                    )
                composition[elem.upper()] = _number(value, f"成分 {key}")
        comp_opt = opts.get("COMPOSITION") or opts.get("COMP")
        if comp_opt:
            for part in re.split(r"[,;]", comp_opt):
                if not part.strip():
                    continue
                if ":" not in part:
                    raise CalculationError(
                        "COMPOSITION 需要 元素:分数 的形式", "例如 COMPOSITION=ZN:0.3"
                    )
                elem_raw, value = part.split(":", 1)
                elem = database.resolve(elem_raw.strip())
                if elem is None:
                    raise CalculationError(
                        f"成分元素 {elem_raw} 不在数据库 {database.name} 中",
                        f"可选元素：{', '.join(database.display_elements)}",
                    )
                composition[elem.upper()] = _number(value, f"成分 {elem_raw}")

        start_t = _number(
            opts.get("START-T") or opts.get("START") or opts.get("START-TEMPERATURE")
            or "2000",
            "START-T",
        )
        step_t = _number(
            opts.get("STEP-T") or opts.get("STEP") or opts.get("STEP-TEMPERATURE") or "5",
            "STEP-T",
        )
        stop = _number(opts.get("STOP", "0.0001"), "STOP")
        liquid = opts.get("LIQUID", "")
        adaptive = _bool(opts.get("ADAPTIVE", "ON"), "ADAPTIVE")
        if "METHOD" in opts:
            method = opts["METHOD"].strip().lower()
        if method not in SCHEIL_METHODS:
            raise CalculationError(
                f"未知凝固方法：{method}", f"可用：{', '.join(SCHEIL_METHODS)}"
            )
        if not composition:
            raise CalculationError(
                "凝固需要至少一个成分",
                "例如 SCHEIL X(ZN)=0.3 START-T=850 STEP-T=1",
            )
        if liquid:
            liquid = _resolve_phase(database, liquid)

        config = ScheilConfig(
            database=database,
            comps=comps,
            phases=phases,
            composition=composition,
            start_temperature=start_t,
            step_temperature=step_t,
            liquid_phase_name=liquid,
            stop=stop,
            adaptive=adaptive,
            method=method,
        )
        self.cb.progress(0, 1, "正在模拟凝固…")
        result = run_solidification(
            config,
            figure=None,
            progress=self._progress_cb(),
            should_cancel=self.cb.is_cancelled,
        )
        state.last_figure = result.figure
        state.last_axes = result.axes
        state.last_frame = result.frame
        state.last_series = []
        title = result.title or "凝固模拟"
        state.last_caption = f"{title}｜{method}"
        self.cb.show_figure(result.figure, result.axes_list(), state.last_caption)
        self.summary.n_results += 1
        extra = "｜已耗尽液相" if result.converged else "｜液相未耗尽"
        self._announce(f"凝固完成：{title}{extra}｜耗时 {result.elapsed_s:.1f} s")

    # ------------------------------------------------------------ ESPEI
    def _cmd_espei(self, state: _State, args: List[str], opts: Dict[str, str],
                   base_dir: Path) -> None:
        from .espei_engine import (
            EspeiSettings,
            parse_aicc_penalty,
            parse_tags,
            run_espei,
        )

        if not args:
            raise CalculationError(
                "ESPEI 需要模式",
                "ESPEI GENERATE / ESPEI MCMC / ESPEI CHECK",
            )
        mode = args[0].strip().lower()
        if mode not in ("generate", "mcmc", "check"):
            raise CalculationError(
                f"未知 ESPEI 模式：{args[0]}", "可用：GENERATE / MCMC / CHECK"
            )

        def _path(key: str, default: str = "") -> str:
            raw = opts.get(key, default)
            if not raw:
                return ""
            return str(_resolve_input(raw, base_dir))

        settings = EspeiSettings(
            mode=mode,
            phase_models=_path("PHASE-MODELS", _path("PHASE_MODELS")),
            datasets=_path("DATASETS"),
            input_db=_path("INPUT-DB", _path("INPUT_DB")),
            output_db=str(_resolve_output(
                opts.get("OUTPUT-DB") or opts.get("OUTPUT_DB") or f"espei_{mode}_out.tdb",
                base_dir,
            )),
            ref_state=opts.get("REF-STATE", opts.get("REF_STATE", "SGTE91")),
            excess_model=opts.get("EXCESS-MODEL", opts.get("EXCESS_MODEL", "linear")),
            ridge_alpha=(
                _number(opts["RIDGE"], "RIDGE")
                if opts.get("RIDGE") or opts.get("RIDGE-ALPHA")
                else None
            ),
            verbosity=int(_number(opts.get("VERBOSITY", "2"), "VERBOSITY")),
            output_dir=str(_resolve_output(opts.get("OUTPUT-DIR", "."), base_dir)),
            iterations=int(_number(opts.get("ITERATIONS", "100"), "ITERATIONS")),
            save_interval=int(_number(opts.get("SAVE-INTERVAL", "1"), "SAVE-INTERVAL")),
            chains_per_parameter=int(
                _number(opts.get("CHAINS", opts.get("CHAINS-PER-PARAMETER", "2")), "CHAINS")
            ),
            chain_std_deviation=_number(
                opts.get("STD-DEV", opts.get("CHAIN-STD-DEVIATION", "0.1")), "STD-DEV"
            ),
            scheduler=opts.get("SCHEDULER", "dask"),
            cores=int(_number(opts.get("CORES", "1"), "CORES")),
            prior=opts.get("PRIOR", "zero").strip().lower(),
        )
        prior_loc = opts.get("PRIOR-LOC") or opts.get("PRIOR_LOC")
        prior_scale = opts.get("PRIOR-SCALE") or opts.get("PRIOR_SCALE")
        if settings.prior == "normal":
            # 官方 Cu-Mg 示例用相对先验；不写这两项时与官方一致
            settings.prior_loc_relative = (
                _number(prior_loc, "PRIOR-LOC") if prior_loc else 1.0
            )
            settings.prior_scale_relative = (
                _number(prior_scale, "PRIOR-SCALE") if prior_scale else 1.0
            )
        tags_text = opts.get("TAGS", "")
        if tags_text and tags_text.lower().endswith((".json", ".yaml", ".yml")):
            tags_text = str(_resolve_input(tags_text, base_dir))
        settings.tags = parse_tags(tags_text)
        settings.aicc_penalty_factor = parse_aicc_penalty(
            opts.get("AICC", opts.get("AICC-PENALTY", ""))
        )
        if opts.get("RIDGE-ALPHA"):
            settings.ridge_alpha = _number(opts["RIDGE-ALPHA"], "RIDGE-ALPHA")
        weights: Dict[str, float] = {}
        for part in re.split(r"[,;]", opts.get("WEIGHTS", "")):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            weights[key.strip().upper()] = _number(value, f"WEIGHTS {key}")
        settings.data_weights = weights

        settings.validate()
        self.cb.progress(0, 1, "正在运行 ESPEI…")
        result = run_espei(
            settings,
            progress=self._progress_cb(),
            should_cancel=self.cb.is_cancelled,
            log=self.cb.log,
        )
        if result.figure is not None:
            state.last_figure = result.figure
            state.last_axes = list(result.axes)
            state.last_frame = None
            state.last_series = []
            state.last_caption = f"ESPEI 拟合｜{mode}"
            self.cb.show_figure(result.figure, list(result.axes), state.last_caption)
            self.summary.n_results += 1
        if result.output_db is not None and mode != "check":
            path = Path(result.output_db)
            self.cb.update_database(path)
            try:
                new_db = load_database(path)
            except CalculationError as exc:
                self.cb.log(f"! 产物数据库载入失败：{exc.user_message}")
            else:
                state.database = new_db
                state.phases = new_db.phase_names
                state.elements = [
                    e for e in state.elements if new_db.resolve(e) is not None
                ]
                if not state.elements and len(new_db.display_elements) == 2:
                    state.elements = list(new_db.display_elements)
                self.cb.update_selection(state.elements, state.phases)
            self.summary.outputs.append(path)
        self._announce(
            f"ESPEI {mode} 完成｜数据集 {result.n_datasets} 个｜"
            f"耗时 {result.elapsed_s:.1f} s"
        )

    # ------------------------------------------------------------ 高通量
    def _cmd_ht(self, state: _State, args: List[str], opts: Dict[str, str],
                base_dir: Path) -> None:
        database = self._db(state)
        comps = self._components(state)
        phases = self._phases(state)
        if not state.sweeps:
            raise CalculationError(
                "高通量至少需要一个 SWEEP",
                "例如 SWEEP T 800 1200 100 与 SWEEP ZN 0 1 0.1",
            )
        sweeps: Dict[str, List[float]] = {}
        for target, (start, stop, step) in state.sweeps.items():
            sweeps[target] = _samples(start, stop, step, f"SWEEP {target}")
        # HTConfig 没有单独的"固定条件"字段：未扫描的定值补成单点轴，
        # 这样 P、X(元素) 之类的固定条件也能真正进入每个计算点
        for target, value in state.fixed.items():
            if target not in sweeps:
                sweeps[target] = [float(value)]
        if "T" not in sweeps:
            sweeps["T"] = [float(state.fixed.get("T", 1200.0))]

        requested = [
            o.strip() for o in re.split(r"[,;]", opts.get("OUTPUTS", "stable_phases,gm_min,n_phases"))
            if o.strip()
        ]
        unknown = [o for o in requested if o not in HT_OUTPUTS]
        if unknown:
            raise CalculationError(
                f"未知输出指标：{', '.join(unknown)}",
                f"可用：{', '.join(HT_OUTPUTS)}",
            )
        parallel = int(_number(opts.get("PARALLEL", "4"), "PARALLEL"))
        use_process = _bool(opts.get("PROCESS", "OFF"), "PROCESS")
        config = HTConfig(
            database=database,
            comps=comps,
            phases=sorted(phases),
            sweeps=sweeps,
            outputs=requested,
            parallel=max(1, parallel),
            use_process_pool=use_process,
        )
        self.cb.progress(0, 1, f"高通量：{config.total_points} 个点…")
        result = run_high_throughput(
            config,
            progress=self._progress_cb(),
            should_cancel=self.cb.is_cancelled,
        )
        state.last_frame = result.frame
        state.last_series = []
        state.last_figure = None
        state.last_caption = ""
        self.cb.show_table(result.frame, "高通量结果")
        self.summary.n_results += 1
        for point, reason in result.failures[:5]:
            self.cb.log(f"! 失败点 {point}：{reason}")
        self._announce(
            f"高通量完成：{result.n_ok}/{result.n_total} 点｜耗时 {result.elapsed_s:.1f} s"
            + (f"｜失败 {result.n_failed} 点" if result.n_failed else "")
        )

    # ------------------------------------------------------------ 导出
    def _cmd_export(self, state: _State, args: List[str], opts: Dict[str, str],
                    base_dir: Path) -> None:
        if not args:
            raise CalculationError("EXPORT 需要输出路径", "例如 EXPORT result.png")
        kind = ""
        first = args[0].upper()
        rest = list(args)
        if first in ("FIGURE", "IMAGE", "PLOT"):
            kind = "figure"
            rest = args[1:]
        elif first in ("DATA", "TABLE"):
            kind = "data"
            rest = args[1:]
        elif first in ("PNG", "SVG", "PDF", "JPG", "JPEG"):
            kind = "figure"
            rest = args[1:] or [f"result.{first.lower().replace('jpeg', 'jpg')}"]
        elif first in ("CSV", "XLSX", "XLS"):
            kind = "data"
            rest = args[1:] or [f"result.{first.lower()}"]
        if not rest:
            raise CalculationError(
                "EXPORT 需要输出路径", "例如 EXPORT FIGURE result.png / EXPORT DATA result.csv"
            )

        path = _resolve_output(rest[0], base_dir)
        suffix = path.suffix.lower().lstrip(".")
        if not kind:
            kind = "data" if suffix in ("csv", "xlsx", "xls") else "figure"

        if kind == "figure":
            if state.last_figure is None:
                raise CalculationError(
                    "还没有可导出的图像", "先运行 DIAGRAM / PROPERTY / SCHEIL 或 ESPEI"
                )
            dpi = int(_number(opts.get("DPI", "200"), "DPI"))
            export_figure(state.last_figure, path, dpi=dpi)
        else:
            if suffix in ("csv", "xlsx", "xls") and state.last_frame is not None:
                export_dataframe(state.last_frame, path)
            elif suffix in ("csv", "xlsx", "xls") and state.last_series:
                export_series_csv(
                    state.last_series, path,
                    x_label=state.last_x_label, y_label=state.last_y_label,
                )
            else:
                raise CalculationError(
                    "当前结果没有可导出的数据表",
                    "高通量 / 凝固 / 属性结果可导出 CSV；相图请导出图像",
                )
        self.summary.outputs.append(path)
        self._announce(f"已导出 {path}")

    # ------------------------------------------------------------ 其它
    def _cmd_print(self, state: _State, args: List[str], opts: Dict[str, str],
                   base_dir: Path) -> None:
        if args:
            self.cb.log(" ".join(args))

    def _cmd_set(self, state: _State, args: List[str], opts: Dict[str, str],
                 base_dir: Path) -> None:
        if len(args) < 2:
            raise CalculationError("SET 需要 名称 值", "例如 SET temp 850")
        name = args[0].lstrip("$")
        state.variables[name] = " ".join(args[1:])
        self.cb.log(f"$ {name} = {state.variables[name]}")

    def _cmd_include(self, state: _State, args: List[str], opts: Dict[str, str],
                     base_dir: Path) -> None:
        if not args:
            raise CalculationError("INCLUDE 需要宏文件路径", "例如 INCLUDE common/load.tdb.mcm")
        path = _resolve_input(args[0], base_dir)
        if not path.is_file():
            raise CalculationError(f"找不到被引用的宏文件：{args[0]}", f"解析后路径：{path}")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise CalculationError(f"无法读取宏文件：{path.name}", str(exc)) from exc
        self.cb.log(f"# INCLUDE {path}")
        self.execute_text(text, state, path.parent, depth=self._depth + 1)

    @property
    def _depth(self) -> int:
        """当前正在执行的文件深度（根宏为 0，INCLUDE 每层 +1）。"""
        return self._depth_stack[-1] if self._depth_stack else 0

    def _cmd_reset(self, state: _State, args: List[str], opts: Dict[str, str],
                   base_dir: Path) -> None:
        state.reset_conditions()
        self._announce("已重置扫描条件、固定条件与绘图选项")

    def _cmd_show(self, state: _State, args: List[str], opts: Dict[str, str],
                  base_dir: Path) -> None:
        database = state.database
        if database is None:
            self.cb.log("状态：尚未载入数据库")
            return
        what = args[0].upper() if args else "ALL"
        if what in ("ALL", "DATABASE", "DB"):
            self.cb.log(f"数据库：{database.name}（{database.path}）")
        if what in ("ALL", "ELEMENTS"):
            self.cb.log("元素：" + (" + ".join(state.elements) if state.elements else "（未选择）"))
        if what in ("ALL", "PHASES"):
            self.cb.log(f"相（{len(state.phases)}）：{', '.join(state.phases)}")
        if what in ("ALL", "CONDITIONS", "COND"):
            sweeps = "; ".join(
                f"{k} {a:g}→{b:g} step {c:g}" for k, (a, b, c) in state.sweeps.items()
            )
            fixed = ", ".join(f"{k}={v:g}" for k, v in state.fixed.items())
            self.cb.log(f"扫描：{sweeps or '（未设置）'}｜固定：{fixed or '（未设置）'}")


__all__ = [
    "MacroCallbacks",
    "MacroCancelled",
    "MacroResult",
    "MacroSession",
    "run_macro_file",
    "run_macro_text",
    "MAX_SAMPLES",
]

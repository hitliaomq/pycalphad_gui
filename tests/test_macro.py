"""宏解释器与宏示例的无界面测试。

覆盖：词法（注释 / 变量 / 引号 / 续行）、INCLUDE、错误行号、相图 / 属性 /
凝固 / 高通量 / ESPEI CHECK 的端到端执行，以及示例宏目录的完整性。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

from pycalphad_gui.core.diagnostics import CalculationError  # noqa: E402
from pycalphad_gui.core.macro_engine import (  # noqa: E402
    MacroCallbacks,
    MacroSession,
    run_macro_file,
    run_macro_text,
)
from pycalphad_gui.core.macro_help import (  # noqa: E402
    command_names,
    help_for,
    help_overview,
    help_request,
)

DB_DIR = Path(__file__).parent / "databases" / "pycalphad"
BIN_DB = DB_DIR / "alzn_mey.tdb"
MACROS = ROOT / "macros"


class _Recorder:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.figures: list[tuple] = []
        self.tables: list[tuple] = []
        self.databases: list[str] = []
        self.selections: list[tuple] = []

    @property
    def callbacks(self) -> MacroCallbacks:
        return MacroCallbacks(
            log=self.logs.append,
            figure=lambda fig, axes, cap: self.figures.append((fig, axes, cap)),
            table=lambda df, title: self.tables.append((df, title)),
            database=self.databases.append,
            selection=lambda e, p: self.selections.append((e, p)),
        )


# ---------------------------------------------------------------------------
# 词法与基本命令
# ---------------------------------------------------------------------------
def test_comments_variables_quotes_and_continuation(tmp_path: Path) -> None:
    spaced = tmp_path / "my db.tdb"
    shutil.copy(BIN_DB, spaced)

    text = f"""
    # 井号注释
    // 斜杠注释
    $root = "{tmp_path.as_posix()}"
    OPEN "$root/my db.tdb"   # 行内注释不影响前面
    ELEMENTS AL ZN
    PHASES LIQUID FCC_A1 \\
           HCP_A3
    PRINT "hello # not comment"
    """
    rec = _Recorder()
    result = run_macro_text(text, base_dir=tmp_path, callbacks=rec.callbacks)

    assert result.database_path == spaced
    assert any("hello # not comment" in line for line in rec.logs)
    # PHASES 的续行必须真的把三相当成一行的参数
    assert any(line.startswith("相：") and "HCP_A3" in line for line in rec.logs)


def test_unknown_command_reports_line_number() -> None:
    text = f"OPEN {BIN_DB.as_posix()}\nELEMENTS AL ZN\nFLY TO THE MOON\n"
    try:
        run_macro_text(text, base_dir=DB_DIR)
    except CalculationError as exc:
        assert "第 3 行" in exc.user_message
        assert "FLY" in exc.user_message
    else:
        raise AssertionError("未知命令应抛 CalculationError")


def test_include_resolves_relative_to_including_file(tmp_path: Path) -> None:
    sub = tmp_path / "common"
    sub.mkdir()
    (sub / "setup.pcm").write_text(
        f"OPEN {BIN_DB.as_posix()}\nELEMENTS AL ZN\n", encoding="utf-8"
    )
    (tmp_path / "main.pcm").write_text("INCLUDE common/setup.pcm\n", encoding="utf-8")

    result = run_macro_file(tmp_path / "main.pcm")
    assert result.database_path == BIN_DB


def test_missing_include_is_a_clear_error(tmp_path: Path) -> None:
    try:
        run_macro_text("INCLUDE nope.pcm\n", base_dir=tmp_path)
    except CalculationError as exc:
        assert "找不到被引用的宏文件" in exc.user_message
    else:
        raise AssertionError("缺失的 INCLUDE 应报错")


def test_include_recursion_is_bounded(tmp_path: Path) -> None:
    a = tmp_path / "a.pcm"
    b = tmp_path / "b.pcm"
    a.write_text("INCLUDE b.pcm\n", encoding="utf-8")
    b.write_text("INCLUDE a.pcm\n", encoding="utf-8")
    try:
        run_macro_file(a)
    except CalculationError as exc:
        assert "嵌套" in exc.user_message
    else:
        raise AssertionError("互相 INCLUDE 应被层数上限拦住")


# ---------------------------------------------------------------------------
# 交互式会话（命令面板用）
# ---------------------------------------------------------------------------
def test_session_keeps_state_across_lines() -> None:
    rec = _Recorder()
    session = MacroSession(
        base_dir=DB_DIR,
        callbacks=rec.callbacks,
        initial_database=str(BIN_DB),
        initial_elements=["AL", "ZN"],
    )
    # 初始数据库是懒加载的：还没执行命令就不该读 TDB
    assert not session.started and session.database is None

    assert session.run_line("ELEMENTS AL ZN").n_commands == 1
    assert session.run_line("SWEEP ZN 0 1 0.1").n_commands == 1
    assert session.run_line("FIXED T=600 P=101325").n_commands == 1
    session.run_line("$temp = 700")
    session.run_line('PRINT "temp=$temp"')

    assert session.database is not None and session.database.path == BIN_DB
    assert session.elements == ["AL", "ZN"]
    assert session.variables["temp"] == "700"
    assert "temp=700" in rec.logs

    # 条件必须留在会话里，下一条 SHOW 才能看到
    rec.logs.clear()
    session.run_line("SHOW")
    text = "\n".join(rec.logs)
    assert "ZN 0→1" in text and "T=600" in text, text


def test_session_survives_an_error_without_line_numbers() -> None:
    session = MacroSession(
        base_dir=DB_DIR,
        initial_database=str(BIN_DB),
        initial_elements=["AL", "ZN"],
    )
    session.run_line("ELEMENTS AL ZN")
    try:
        session.run_line("FLY TO THE MOON")
    except CalculationError as exc:
        assert "FLY" in exc.user_message
        assert "第 1 行" not in exc.user_message, "交互式命令不该带行号前缀"
    else:
        raise AssertionError("未知命令应抛 CalculationError")

    # 出错后栈深度必须复原，否则 INCLUDE 的可用层数会越来越少
    assert session._runner._depth_stack == []
    assert session.run_line("SHOW").n_commands == 1


# ---------------------------------------------------------------------------
# 帮助文本
# ---------------------------------------------------------------------------
def test_help_overview_and_per_command() -> None:
    overview = help_overview()
    for name in command_names():
        assert name in overview, f"总览漏了 {name}"

    detail = help_for("load")  # 别名应解析到 OPEN
    assert detail is not None
    assert detail.startswith("OPEN")
    assert "OPEN <TDB/DAT>" in detail and "示例：" in detail
    assert help_for("NOPE") is None

    ok, text, query = help_request("?")
    assert ok and text == overview and query == ""
    ok, text, query = help_request("OPEN ?")
    assert ok and "OPEN <TDB/DAT>" in text and query == "OPEN"
    ok, text, query = help_request("? SCHEIL")
    assert ok and text.startswith("SCHEIL") and query == "SCHEIL"
    ok, text, query = help_request("NOPE ?")
    assert ok and text is None and query == "NOPE"
    assert help_request("PHASES LIQUID FCC_A1") == (False, None, "")


def test_macro_help_is_fully_translated() -> None:
    from pycalphad_gui import i18n

    texts = [help_overview()] + [help_for(name) for name in command_names()]
    for text in texts:
        english = i18n.tr_to(text, "en")
        assert not i18n.has_cjk(english), f"帮助没翻干净：{english}"


# ---------------------------------------------------------------------------
# 端到端：相图 / 属性 / 凝固 / 高通量
# ---------------------------------------------------------------------------
def test_binary_diagram_macro_exports_figure(tmp_path: Path) -> None:
    text = f"""
    OPEN {BIN_DB.as_posix()}
    ELEMENTS AL ZN
    PHASES LIQUID FCC_A1 HCP_A3
    SWEEP ZN 0 1 0.2
    SWEEP T 400 900 100
    FIXED P=101325
    DIAGRAM BINARY
    EXPORT FIGURE {tmp_path.as_posix()}/diagram.png
    """
    rec = _Recorder()
    result = run_macro_text(text, base_dir=tmp_path, callbacks=rec.callbacks)

    assert result.n_results == 1
    assert rec.figures and rec.figures[0][0].axes, "应产出带坐标轴的相图"
    png = tmp_path / "diagram.png"
    assert png.is_file() and png.stat().st_size > 1000


def test_diagram_has_no_data_table_to_export(tmp_path: Path) -> None:
    text = f"""
    OPEN {BIN_DB.as_posix()}
    ELEMENTS AL ZN
    SWEEP ZN 0 1 0.5
    SWEEP T 500 600 100
    DIAGRAM BINARY
    EXPORT DATA {tmp_path.as_posix()}/bad.csv
    """
    try:
        run_macro_text(text, base_dir=tmp_path)
    except CalculationError as exc:
        assert "没有可导出的数据表" in exc.user_message
    else:
        raise AssertionError("相图结果不应能导出数据表")


def test_property_macro_exports_csv(tmp_path: Path) -> None:
    text = f"""
    OPEN {BIN_DB.as_posix()}
    ELEMENTS AL ZN
    PHASES LIQUID FCC_A1 HCP_A3
    PROPERTY NP VS T FROM 450 TO 650 STEP 25 X(ZN)=0.3
    EXPORT FIGURE {tmp_path.as_posix()}/np.png
    EXPORT DATA {tmp_path.as_posix()}/np.csv
    """
    rec = _Recorder()
    result = run_macro_text(text, base_dir=tmp_path, callbacks=rec.callbacks)

    assert result.n_results == 1
    assert rec.figures and rec.figures[0][0].axes
    csv = tmp_path / "np.csv"
    assert csv.is_file()
    assert "T" in csv.read_text(encoding="utf-8").splitlines()[0]


def test_scheil_macro_runs_and_exports(tmp_path: Path) -> None:
    text = f"""
    OPEN {BIN_DB.as_posix()}
    ELEMENTS AL ZN
    PHASES LIQUID FCC_A1 HCP_A3
    SCHEIL X(ZN)=0.3 START-T=850 STEP-T=2 LIQUID=LIQUID
    EXPORT FIGURE {tmp_path.as_posix()}/scheil.png
    EXPORT DATA {tmp_path.as_posix()}/scheil.csv
    """
    rec = _Recorder()
    result = run_macro_text(text, base_dir=tmp_path, callbacks=rec.callbacks)

    assert result.n_results == 1
    assert rec.figures and rec.figures[0][0].axes
    assert (tmp_path / "scheil.csv").is_file()


def test_high_throughput_macro_emits_table(tmp_path: Path) -> None:
    text = f"""
    OPEN {BIN_DB.as_posix()}
    ELEMENTS AL ZN
    PHASES LIQUID FCC_A1 HCP_A3
    SWEEP T 500 700 100
    SWEEP ZN 0.2 0.4 0.2
    HT OUTPUTS=stable_phases,n_phases PARALLEL=2
    EXPORT DATA {tmp_path.as_posix()}/ht.csv
    """
    rec = _Recorder()
    result = run_macro_text(text, base_dir=tmp_path, callbacks=rec.callbacks)

    assert result.n_results == 1
    assert rec.tables and len(rec.tables[0][0]) == 6
    assert (tmp_path / "ht.csv").is_file()


# ---------------------------------------------------------------------------
# ESPEI 集成与示例目录
# ---------------------------------------------------------------------------
def test_espei_check_macro_validates_bundled_datasets() -> None:
    rec = _Recorder()
    result = run_macro_file(MACROS / "espei" / "01_check_datasets.pcm", callbacks=rec.callbacks)
    assert result.n_results == 0, "CHECK 不产出图像"
    assert result.outputs == []
    assert any("校验" in line for line in rec.logs)


def test_bundled_macros_are_readable_and_mention_upstream() -> None:
    files = sorted(MACROS.glob("*/*.pcm"))
    assert len(files) >= 22, f"示例宏数量异常：{len(files)}"
    assert not list(MACROS.rglob("*.m")), "宏文件统一使用 .pcm 后缀"
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        assert text.strip(), f"{path} 是空文件"
        assert "对应文档" in text or "http" in text, \
            f"{path} 头注释应给出对应上游示例"
        assert "OPEN" in text or "ESPEI" in text or "INCLUDE" in text, \
            f"{path} 没有载入数据库或调用 ESPEI"

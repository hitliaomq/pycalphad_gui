"""ESPEI 与 Scheil 两个子面板的回归测试。

分三层：

1. **引擎层**（不需要 Qt）：scheil 真跑一遍凝固模拟，espei 校验数据集 + 真跑一遍
   generate_parameters 产 TDB。这两条是"功能存在"的底线，上游 API 一变就会红。
2. **面板层**：ESPEI / Scheil 两个 Tab 能构造、能拒绝非法输入、切库时成分不丢。
3. **GUI 层**：主窗口里点一次「开始凝固模拟」，走完整的
   ``线程 → 引擎 → set_figure`` 链路，断言画布上真有线、进度条推满。

运行：``python tests/test_espei_scheil.py``（也可交给 pytest 收集）。
缺 espei/scheil 时前两层自动跳过——它们只是本机装了包，不是运行时依赖。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

# 让脚本在没有安装成包时也能导入；离屏必须早于任何 Qt 导入
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if not os.environ.get("QT_QPA_PLATFORM"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import matplotlib  # noqa: E402
import numpy as np  # noqa: E402

matplotlib.use("Agg")

#: 本仓库内置的 ESPEI 官方 Cu-Mg 教程数据
MACRO_ESPEI = ROOT / "macros" / "espei"

#: V–Zr 库（液相叫 IONIC_LIQ 而非 LIQUID，专门用来压 guess_liquid_phase）
VZR_DB = ROOT / "tests" / "databases" / "vzr_zha-2012.tdb"

results: list = []


def check(name: str, fn) -> None:
    """注册制检查；单个失败不影响其余用例。"""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, f"{type(exc).__name__}: {exc}"))
        print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    else:
        results.append((name, True, ""))
        print(f"ok   {name}")


def _skip(reason: str):
    print(f"skip（{reason}）")


#: 必须**持有** QApplication 的引用。它是局部变量时会被 GC 回收，
#: 之后构造任何 QWidget 都会把进程直接带崩（不是抛异常，try/except 兜不住）。
_APP = None


def _app():
    """保证存在一个 QApplication，并返回它（调用方要保证引用不丢）。"""
    global _APP
    from PyQt6.QtWidgets import QApplication

    if _APP is None:
        instance = QApplication.instance()
        _APP = instance if instance is not None else QApplication([])
    return _APP


# 模块导入时就建好 QApplication：任何 QWidget 构造之前都必须有活着的实例
_app()


# ================================================================ 引擎层： scheil
def _scheil_available() -> bool:
    try:
        import scheil  # noqa: F401
    except ImportError:
        return False
    return VZR_DB.is_file()


def _scheil_db():
    from pycalphad_gui.core.database_manager import load_database

    return load_database(VZR_DB)


def test_scheil_engine_runs_and_plots() -> None:
    """真跑一次 Scheil 凝固：出图、出表、出中文摘要。"""
    from pycalphad_gui.core.scheil_engine import ScheilConfig, run_solidification

    db = _scheil_db()
    config = ScheilConfig(
        database=db,
        comps=db.components_for(["V", "Zr"]),
        phases=list(db.phase_names),
        composition={"V": 0.7, "Zr": 0.3},
        start_temperature=2500.0,
        step_temperature=25.0,
    )
    result = run_solidification(config)

    assert not result.frame.empty, "结果表不应为空"
    assert "温度 (K)" in result.frame.columns, list(result.frame.columns)
    assert len(result.frame) > 1, f"温度步数过少：{len(result.frame)}"
    assert result.summary, "摘要不应为空"
    for key in ("方法", "起点温度 (K)", "终点温度 (K)", "是否收敛"):
        assert key in result.summary, f"摘要缺少 {key}：{list(result.summary)}"

    # 曲线必须落在初始视野里（T46 的同类回归：范围停在 (0,1) 就是没画出来）。
    # 注意温度轴是**反向**的，所以"覆盖"要按 min/max 的绝对意义判断。
    temps = result.frame["温度 (K)"].to_numpy(dtype=float)
    xs, ys = result.axes.get_xlim(), result.axes.get_ylim()
    assert min(xs) <= temps.min(), f"x 轴未覆盖数据：{xs} vs {temps.min()}"
    assert max(xs) >= temps.max(), f"x 轴未覆盖数据：{xs} vs {temps.max()}"
    assert ys[1] > ys[0], f"y 轴范围异常：{ys}"
    assert result.axes.get_autoscale_on() is False, "画布接管后应关闭 autoscale"

    # 凝固图的习惯画法：从左到右降温，x 轴必须反向
    assert xs[0] > xs[1], f"温度轴应反向（起点在左），实际 {xs}"
    # 物理自洽：温度只降不升，且这个成分点最终应完全凝固
    temps = result.frame["温度 (K)"].to_numpy(dtype=float)
    assert (np.diff(temps) <= 0).all(), "温度序列必须单调下降"
    assert result.frame["固相分数"].to_numpy(dtype=float)[-1] >= 1.0 - 1e-6, (
        f"V-30Zr 在 vzr 库里应当走完全部液相：{result.frame['固相分数'].to_numpy(dtype=float)[-1]}"
    )
    # scheil 的 converged 在"步数用尽"时也可能为 False，但固相分数已到 1 就说明跑完了；
    # 摘要必须如实反映这一点（面板的提示文案依赖它，别改坏了）
    assert str(result.summary["是否收敛"]).startswith("是"), result.summary["是否收敛"]


def test_scheil_engine_equilibrium_method() -> None:
    """平衡凝固走的是另一个入口，不能只在 scheil 分支上测。"""
    from pycalphad_gui.core.scheil_engine import ScheilConfig, run_solidification

    db = _scheil_db()
    result = run_solidification(
        ScheilConfig(
            database=db,
            comps=db.components_for(["V", "Zr"]),
            phases=list(db.phase_names),
            composition={"V": 0.7, "Zr": 0.3},
            start_temperature=2500.0,
            step_temperature=50.0,
            method="equilibrium",
        )
    )
    assert "平衡凝固" in result.summary["方法"], result.summary["方法"]
    assert len(result.frame) > 1


def test_scheil_engine_liquid_phase_guess() -> None:
    """vzr 库的液相叫 IONIC_LIQ，猜错会直接崩，这条锁住推断逻辑。"""
    from pycalphad_gui.core.scheil_engine import guess_liquid_phase

    db = _scheil_db()
    assert guess_liquid_phase(db, list(db.phase_names)) == "IONIC_LIQ"


def test_scheil_engine_rejects_bad_composition() -> None:
    """摩尔分数之和 >= 1 时要在引擎层就地报错，不能丢给 scheil 抛自由度异常。"""
    from pycalphad_gui.core.diagnostics import CalculationError
    from pycalphad_gui.core.scheil_engine import ScheilConfig

    db = _scheil_db()
    config = ScheilConfig(
        database=db,
        comps=db.components_for(["V", "Zr"]),
        phases=list(db.phase_names),
        # 二元体系里"第一个元素"就是独立组分，它自己顶到 1 时 VA 的余额为负
        composition={"V": 1.0, "Zr": 0.5},
    )
    try:
        config.build()
    except CalculationError as exc:
        assert "1" in exc.detail, exc.detail
    else:  # pragma: no cover - 上游若改了校验规则，这条会立刻暴露
        raise AssertionError("成分之和 > 1 应当被拒绝")


# ================================================================ 引擎层： espei
_ESPEI_PHASE_MODELS = {
    "components": ["MG", "ZN"],
    "phases": {
        "LIQUID": {
            "crystal": "FLUID",
            "sublattice_model": [["MG", "ZN"]],
            "sublattice_site_ratios": [1],
        },
        "FCC_A3": {
            "crystal": "FCC",
            "mix": True,
            "sublattice_model": [["MG", "ZN"]],
            "sublattice_site_ratios": [1],
        },
    },
}

#: 注意 values 的层级：[[[相, [组分], [x]], ...]] —— Outer list 是"数据集条目"，
#: 再往里一层才是 tieline。少一层会让 ESPEI 报 ZPF shape 不合法。
#: reference 刻意只用 ASCII：ESPEI 0.9.1 的 load_datasets 用系统默认编码
#: （中文 Windows 上是 cp936）读 JSON，写汉字会在校验阶段直接 UnicodeDecodeError。
_ESPEI_DATASET = {
    "__data_type__": "ZPF",
    "output": "ZPF",
    "tags": [],
    "components": ["MG", "ZN", "VA"],
    "phases": ["LIQUID", "FCC_A3"],
    "reference": "pyCalphad GUI regression dataset",
    "conditions": {"P": 101325, "T": [600.0, 700.0]},
    "values": [
        [["FCC_A3", ["MG"], [0.6]], ["LIQUID", ["MG"], [0.6]]],
        [["FCC_A3", ["MG"], [0.8]], ["LIQUID", ["MG"], [0.8]]],
    ],
}


def _espei_available() -> bool:
    try:
        import espei  # noqa: F401
    except ImportError:
        return False
    return True


def _make_espei_project(root: Path) -> Path:
    """造一套最小可用的 ESPEI 工程（数据集 + 相模型 + 输出）。"""
    datasets = root / "datasets"
    datasets.mkdir(parents=True, exist_ok=True)
    (datasets / "zpf.json").write_text(
        json.dumps(_ESPEI_DATASET, ensure_ascii=False), encoding="utf-8"
    )
    (root / "phase_models.json").write_text(
        json.dumps(_ESPEI_PHASE_MODELS, ensure_ascii=False), encoding="utf-8"
    )
    return root


def test_espei_settings_validate() -> None:
    """缺文件要在点按钮的瞬间报错，而不是等 ESPEI 跑到一半。"""
    from pycalphad_gui.core.diagnostics import CalculationError
    from pycalphad_gui.core.espei_engine import EspeiSettings

    settings = EspeiSettings(mode="generate", phase_models="", datasets="x")
    try:
        settings.validate()
    except CalculationError as exc:
        assert "phase_models" in exc.user_message, exc.user_message
    else:  # pragma: no cover
        raise AssertionError("phase_models 为空应当被拒绝")

    settings = EspeiSettings(
        mode="generate",
        phase_models=str(ROOT / "不存在.json"),
        datasets=str(ROOT),
    )
    try:
        settings.validate()
    except CalculationError as exc:
        assert "找不到" in exc.user_message, exc.user_message
    else:  # pragma: no cover
        raise AssertionError("phase_models 不存在应当被拒绝")

    # MCMC 模式必须有起始数据库（phase_models 也得给，否则会先卡在上一项检查上）
    settings = EspeiSettings(
        mode="mcmc",
        phase_models=str(VZR_DB),
        input_db="",
        datasets=str(ROOT),
    )
    try:
        settings.validate()
    except CalculationError as exc:
        assert "起始数据库" in exc.user_message, exc.user_message
    else:  # pragma: no cover
        raise AssertionError("MCMC 缺 input_db 应当被拒绝")


def test_espei_check_datasets() -> None:
    """校验模式只检查、不训练，返回的数据集数要和目录里的一致。"""
    from pycalphad_gui.core.espei_engine import check_datasets

    with tempfile.TemporaryDirectory() as tmp:
        project = _make_espei_project(Path(tmp))
        result = check_datasets(str(project / "datasets"))
    assert result.n_datasets == 1, result.n_datasets
    assert result.mode == "check"
    assert result.output_db is None, "校验模式不该产出 TDB"


def test_espei_tags_and_aicc_parsing() -> None:
    """官方 Cu-Mg 的两个关键设置要能按宏里的简写解析成 ESPEI 的嵌套字典。"""
    from pycalphad_gui.core.espei_engine import parse_aicc_penalty, parse_tags

    tags = parse_tags("dft:-idmix,-mag;estimated-entropy:-idmix,-mag,weight=0.1")
    assert tags == {
        "dft": {"excluded_model_contributions": ["idmix", "mag"]},
        "estimated-entropy": {
            "excluded_model_contributions": ["idmix", "mag"],
            "weight": 0.1,
        },
    }, tags
    assert parse_tags("") == {}
    assert parse_tags('{"dft": {"weight": 2}}')["dft"]["weight"] == 2

    aicc = parse_aicc_penalty("LIQUID:HM=1.4,LIQUID:SM=1.4")
    assert aicc == {"LIQUID": {"HM": 1.4, "SM": 1.4}}, aicc
    assert parse_aicc_penalty("") is None
    assert parse_aicc_penalty('{"LIQUID": {"HM": 2}}')["LIQUID"]["HM"] == 2


def test_espei_run_settings_forward_tags_aicc_and_prior() -> None:
    """GUI / 宏收集到的 tags、AICc、normal 先验必须原样落到 ESPEI run_settings。"""
    from pycalphad_gui.core.espei_engine import (
        EspeiSettings,
        _build_run_settings,
        parse_aicc_penalty,
        parse_tags,
    )

    generate = EspeiSettings(
        mode="generate",
        phase_models=str(MACRO_ESPEI / "data" / "cu-mg" / "phase_models.json"),
        datasets=str(MACRO_ESPEI / "data" / "cu-mg" / "input-data"),
        tags=parse_tags("dft:-idmix,-mag"),
        aicc_penalty_factor=parse_aicc_penalty("LIQUID:HM=1.4"),
    )
    settings = _build_run_settings(generate)
    assert settings["system"]["tags"] == {
        "dft": {"excluded_model_contributions": ["idmix", "mag"]}
    }
    assert settings["generate_parameters"]["aicc_penalty_factor"] == {
        "LIQUID": {"HM": 1.4}
    }

    mcmc = EspeiSettings(
        mode="mcmc",
        phase_models=str(MACRO_ESPEI / "data" / "cu-mg" / "phase_models.json"),
        datasets=str(MACRO_ESPEI / "data" / "cu-mg" / "input-data"),
        input_db=str(VZR_DB),
        scheduler="none",
        prior="normal",
        prior_loc_relative=1.0,
        prior_scale_relative=1.0,
    )
    settings = _build_run_settings(mcmc)
    assert settings["mcmc"]["scheduler"] is None
    assert settings["mcmc"]["prior"] == {
        "name": "normal", "loc_relative": 1.0, "scale_relative": 1.0
    }


def test_espei_official_cu_mg_generate_matches_tutorial() -> None:
    """内置官方数据 + 官方 tags/AICc 应复现教程的 19 个参数（不是 21 个）。"""
    from pycalphad_gui.core import espei_engine
    from pycalphad_gui.core.espei_engine import (
        EspeiSettings,
        parse_aicc_penalty,
        parse_tags,
        run_espei,
    )

    if not (MACRO_ESPEI / "data" / "cu-mg" / "phase_models.json").is_file():
        _skip("缺少内置 Cu-Mg 教程数据")
        return

    original_plot = espei_engine._plot_fit
    espei_engine._plot_fit = lambda *args, **kwargs: (None, [])
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out_db = Path(tmp) / "Cu-Mg-generated.tdb"
            settings = EspeiSettings(
                mode="generate",
                phase_models=str(MACRO_ESPEI / "data" / "cu-mg" / "phase_models.json"),
                datasets=str(MACRO_ESPEI / "data" / "cu-mg" / "input-data"),
                output_db=str(out_db),
                tags=parse_tags(
                    "dft:-idmix,-mag;estimated-entropy:-idmix,-mag,weight=0.1"
                ),
                aicc_penalty_factor=parse_aicc_penalty("LIQUID:HM=1.4,LIQUID:SM=1.4"),
                verbosity=2,
            )
            result = run_espei(settings)
            assert result.n_datasets == 31, result.n_datasets
            text = result.output_db.read_text(encoding="utf-8", errors="ignore")
            params = [line for line in text.splitlines()
                      if line.strip().startswith("PARAMETER ")]
            assert len(params) == 19, f"参数个数与官方不一致：{len(params)}"
            assert "L(LIQUID,CU,MG;1)" in text
            assert "L(LIQUID,CU,MG;2)" not in text, "AICc 未生效，液相多拟合了参数"
            assert any("-34437.58" in line for line in result.log_lines), \
                "液相 L0 的常数项与官方教程不一致"
    finally:
        espei_engine._plot_fit = original_plot


def test_espei_generate_parameters_produces_tdb() -> None:
    """generate 模式端到端：ESPEI 必须真的写出一份能再被 pycalphad 读的 TDB。"""
    from pycalphad_gui.core.espei_engine import EspeiSettings, run_espei

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project = _make_espei_project(root)
        out_db = root / "espei_out.tdb"
        settings = EspeiSettings(
            mode="generate",
            phase_models=str(project / "phase_models.json"),
            datasets=str(project / "datasets"),
            output_db=str(out_db),
            verbosity=1,
        )
        settings.validate()
        result = run_espei(settings)
        # 断言必须留在临时目录的作用域**内**：with 一退出 ESPEI 的临时目录就被删了，
        # 之后再读产物只会得到"路径不存在"
        assert result.output_db is not None, "generate 模式应当给出产物路径"
        assert result.output_db.is_file(), (
            f"产物不存在：{result.output_db}｜目录内容：{sorted(p.name for p in root.iterdir())}"
        )
        assert result.output_db.stat().st_size > 0, "产物是空文件"
        assert result.n_datasets == 1, result.n_datasets
        # 产出的 TDB 必须还能被主流程读回来（这条锁的是 save_database 的写出格式）
        from pycalphad_gui.core.database_manager import load_database

        reloaded = load_database(result.output_db)
        assert reloaded.phases, "重新载入的库里应当有相"
        # 拟合完要顺手出一张「计算 vs 实验数据」对比图（二元体系数据集）
        assert result.figure is not None, "generate 拟合应产出对比图"
        assert result.axes, "对比图应带坐标轴"


# ================================================================ 面板层
def test_espei_tab_rejects_unknown_weight() -> None:
    """数据权重写错要就地拦下，别等 ESPEI 报 schema 错误。"""
    from PyQt6.QtWidgets import QApplication

    from pycalphad_gui.ui.espei_tab import EspeiTab, _parse_data_weights

    app = QApplication.instance() or QApplication([])
    assert app is not None

    from pycalphad_gui.core.diagnostics import CalculationError

    try:
        _parse_data_weights("ZPF=1.0, 混合=2")
    except CalculationError as exc:
        # 「混合=2」里有等号，走的是"键不合法"分支；没等号才会报"格式不正确"
        assert "不是合法键" in exc.user_message, exc.user_message
    else:  # pragma: no cover
        raise AssertionError("非法权重应当被拒绝")

    try:
        _parse_data_weights("ZPF 1.0")
    except CalculationError as exc:
        assert "格式不正确" in exc.user_message, exc.user_message
    else:  # pragma: no cover
        raise AssertionError("缺等号的权重串应当被拒绝")

    assert _parse_data_weights("") == {}, "空串应视为不设置权重"
    assert _parse_data_weights("zpf=0.5") == {"ZPF": 0.5}, "键应忽略大小写"

    tab = EspeiTab()
    assert tab._mode.count() == 3, "应有 generate/mcmc/check 三种模式"


def test_espei_tab_defaults_follow_database() -> None:
    """载入数据库后，ESPEI 的输出 TDB 默认落在数据库同目录（相对路径会丢产物）。"""
    from PyQt6.QtWidgets import QApplication

    from pycalphad_gui.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_database(VZR_DB)

    text = win._espei_tab._output_db.text()
    assert text, "输出路径不应为空"
    assert os.path.isabs(text) or text.endswith("espei_out.tdb"), text
    if os.path.isabs(text):
        assert Path(text).parent == VZR_DB.parent, text


def test_scheil_tab_composition_survives_reconfigure() -> None:
    """换库/切元素重建成分行时，能保留的原值必须保留（ESPEI→TDB→再算相图会走这条路）。"""
    from PyQt6.QtWidgets import QApplication

    from pycalphad_gui.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_database(VZR_DB)

    win._scheil_tab._comp_widgets["V"].setValue(0.42)
    win._scheil_tab._comp_widgets["ZR"].setValue(0.58)
    # 模拟「ESPEI 产物入库」导致的再次 configure
    win._apply_context(win._table.selection())

    assert win._scheil_tab._comp_widgets["V"].value() == 0.42, (
        f"成分值被重建清空：{win._scheil_tab._comp_widgets['V'].value()}"
    )
    # 换库后仍未计算的图要清空，否则会挂着上一轮的曲线
    assert win._scheil_tab._result is None


def test_canvas_clear_figure() -> None:
    """切库清屏走 clear_figure（set_figure 不接受 None）。"""
    from pycalphad_gui.core.scheil_engine import ScheilConfig, run_solidification
    from pycalphad_gui.ui.interactive_canvas import InteractiveCanvas

    _app()
    db = _scheil_db()
    result = run_solidification(
        ScheilConfig(
            database=db,
            comps=db.components_for(["V", "Zr"]),
            phases=list(db.phase_names),
            composition={"V": 0.7, "Zr": 0.3},
            start_temperature=2500.0,
            step_temperature=50.0,
        )
    )
    holder = InteractiveCanvas()
    holder.set_figure(result.figure, result.axes_list())
    assert holder._figure is not None
    holder.clear_figure()
    assert holder._figure is None, "clear_figure 后不应再持有 figure"
    assert holder._axes == [], "清除后坐标轴列表应为空"


# ================================================================ GUI 层
def _wait_for(predicate, timeout: float = 180.0) -> bool:
    """主线程轮询工作线程的结果（工作线程里起 QTimer 不会到达事件循环）。"""
    from PyQt6.QtWidgets import QApplication

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.05)
    return predicate()


def test_scheil_tab_end_to_end_curve() -> None:
    """主窗口里点一次「开始凝固模拟」，画布上必须真有曲线、进度条必须推满。"""
    from PyQt6.QtWidgets import QApplication

    from pycalphad_gui.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_database(VZR_DB)
    win.show()  # 必须先显示，子控件布局才是真的

    tab = win._scheil_tab
    tab._comp_widgets["V"].setValue(0.7)
    tab._comp_widgets["ZR"].setValue(0.3)
    tab._start_t.setValue(2500.0)
    tab._step_t.setValue(25.0)
    tab._liquid.setText("IONIC_LIQ")

    tab._on_run()

    done = _wait_for(lambda: tab._result is not None)
    assert done, "凝固模拟应在超时前完成（且没有卡在中途）"
    assert not tab._btn_run.isEnabled() is False, "运行按钮应在结束时恢复"
    assert tab._progress.value() == tab._progress.maximum(), (
        f"成功收尾必须推满进度条：{tab._progress.value()}/{tab._progress.maximum()}"
    )

    result = tab._result
    assert result is not None
    line = result.axes.get_lines()
    assert len(line) >= 1, "图上至少应有一条曲线（固相总量）"
    xd = line[0].get_xdata()
    assert xd.size > 1, "曲线点数过少"
    # 视野必须覆盖曲线（T46 的同类回归）；x 轴反向，所以按绝对大小比
    xs = result.axes.get_xlim()
    assert min(xs) <= xd.min(), f"视野未覆盖曲线：{xs} vs {xd.min()}"
    assert max(xs) >= xd.max(), f"视野未覆盖曲线：{xs} vs {xd.max()}"
    assert tab._btn_export.isEnabled(), "有结果后导出按钮应可用"
    assert "✅" in tab._info.text(), tab._info.text()


def test_espei_database_ready_loads_into_window() -> None:
    """ESPEI 页的「载入到主窗口」必须真的换掉当前数据库。"""
    from PyQt6.QtWidgets import QApplication

    from pycalphad_gui.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.load_database(VZR_DB)
    win._espei_tab.database_ready.emit(str(VZR_DB))

    assert win._database is not None, "信号应该触发数据库重载"
    assert Path(str(win._database.path)) == VZR_DB, win._database.path


# ================================================================ 入口
def main() -> int:
    total = 0
    passed = 0

    def run(name: str, fn) -> None:
        nonlocal total, passed
        check(name, fn)
        total += 1
        passed += sum(1 for n, ok, _ in results if ok and n == name)

    if _scheil_available():
        run("scheil 引擎真跑一遍（出图/出表/出摘要）", test_scheil_engine_runs_and_plots)
        run("平衡凝固分支", test_scheil_engine_equilibrium_method)
        run("液相名推断（IONIC_LIQ）", test_scheil_engine_liquid_phase_guess)
        run("非法成分被就地拒绝", test_scheil_engine_rejects_bad_composition)
        run("画布 clear_figure", test_canvas_clear_figure)
        run("面板：凝固页切库不丢成分", test_scheil_tab_composition_survives_reconfigure)
        run("GUI：凝固页端到端出曲线", test_scheil_tab_end_to_end_curve)
    else:
        _skip("未安装 scheil 或缺少 vzr 测试库")

    if _espei_available():
        run("ESPEI 配置校验（缺文件/缺起始库）", test_espei_settings_validate)
        run("ESPEI 数据集校验模式", test_espei_check_datasets)
        run("ESPEI tags/AICc 简写解析", test_espei_tags_and_aicc_parsing)
        run("ESPEI run_settings 透传 tags/AICc/先验",
            test_espei_run_settings_forward_tags_aicc_and_prior)
        run("官方 Cu-Mg generate 复现教程参数",
            test_espei_official_cu_mg_generate_matches_tutorial)
        run("ESPEI generate 产出可用 TDB", test_espei_generate_parameters_produces_tdb)
        run("面板：ESPEI 权重格式与非空校验", test_espei_tab_rejects_unknown_weight)
        run("面板：ESPEI 输出路径跟随数据库", test_espei_tab_defaults_follow_database)
        run("GUI：ESPEI 产物载入主窗口", test_espei_database_ready_loads_into_window)
    else:
        _skip("未安装 espei")

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n通过 {passed}/{total}")
    for name, ok, msg in results:
        if not ok:
            print(f"  · {name}: {msg}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""应用启动入口。

支持两种等价的运行方式，二者都从主线程启动：

* ``python app.py``            —— 直接运行本文件（脚本模式）
* ``python -m pycalphad_gui``  —— 以包方式运行

本模块刻意同时保留两套导入写法：脚本模式下 ``__main__.__spec__`` 为 ``None``，
importlib 会直接拒绝相对导入（实测把 ``__package__`` 改成包名也救不回来），
因此必须先补 ``sys.path`` 再退回绝对导入。

关键约束：**matplotlib 的后端只能在主线程设置一次**，且必须在创建任何
``FigureCanvas`` 之前。因此后端选择放在 :func:`main` 的最前面。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Optional

# --------------------------------------------------------------- 双模式导入
# 以脚本方式运行（python app.py）时，sys.path[0] 是本文件所在目录，
# 而包在它的上一级，需要补进去才能做绝对导入。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # 包模式：python -m pycalphad_gui
    from .config import APP_NAME, APP_VERSION, LOG_FORMAT
    from .ui.main_window import MainWindow
except ImportError:  # 脚本模式：python app.py
    from pycalphad_gui.config import APP_NAME, APP_VERSION, LOG_FORMAT
    from pycalphad_gui.ui.main_window import MainWindow

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: F401

#: 打开主窗口时直接最大化。
#:
#: 界面是"左画布 + 右侧多页工具"的三栏布局，小窗口下画布会被挤到没法看相图。
#: 做成开关而不是写死：离屏测试要构造出尺寸可控的窗口（offscreen 平台下
#: showMaximized 也会去问屏幕几何，无头环境里拿到的尺寸不可预期）。
START_MAXIMIZED = True


def setup_logging(level: int = logging.INFO, logfile: Optional[Path] = None) -> None:
    """配置根日志；同时输出到控制台与可选文件。"""
    handlers: list = [logging.StreamHandler(sys.stderr)]
    if logfile is not None:
        try:
            logfile.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(logfile, encoding="utf-8"))
        except OSError:
            pass  # 日志不可写不应阻断启动
    logging.basicConfig(level=level, format=LOG_FORMAT, handlers=handlers)


def main(argv: Optional[List[str]] = None) -> int:
    """启动 GUI。

    启动后**不会**自动载入任何数据库，用户需在界面中选择「打开数据库…」
    （工具栏按钮 / 菜单 / 直接把 .tdb 拖进窗口）。命令行仍可接受一个数据库
    路径，用于脚本化启动。

    Parameters
    ----------
    argv
        命令行参数；``None`` 时使用 ``sys.argv``。

    Returns
    -------
    int
        进程退出码。
    """
    argv = list(sys.argv if argv is None else argv)

    # 必须在创建任何画布之前绑定后端，且只做一次。
    #
    # 这里刻意用 Agg 而不是 QtAgg：pycalphad 的 binplot/ternplot/eqplot 会调
    # ``plt.subplots()``，而它们是跑在后台线程里的。若后端是 QtAgg，等于让工作
    # 线程去 new 一个 QWindow —— Qt 要求所有 GUI 对象都在主线程创建，这在 Windows
    # 上会间歇性崩溃。改用 Agg 后，后台只产出"纯 Figure"，真正的 Qt 画布由
    # InteractiveCanvas.set_figure() 在主线程创建并 figure.set_canvas() 挂上。
    import matplotlib

    matplotlib.use("Agg")

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))
    # 主题必须在 QApplication 建好之后、任何窗口出现之前套上去
    try:  # 包模式
        from .ui.theme import apply_cjk_font, apply_theme, application_icon
    except ImportError:  # 脚本模式
        from pycalphad_gui.ui.theme import apply_cjk_font, apply_theme, application_icon

    apply_theme(app)
    # matplotlib 默认字体没有 CJK 字形，标注里的汉字会变豆腐块；
    # 必须在绘图引擎创建任何 Text 对象之前设置（worker 线程也算）。
    apply_cjk_font()
    logo = application_icon()
    if not logo.isNull():
        app.setWindowIcon(logo)

    setup_logging(logfile=Path.home() / ".pycalphad_gui" / "run.log")

    window = MainWindow()
    # 先 show 再最大化：直接 showMaximized 的话，外部工具（比如 tests/
    # test_entry.py 的自动退出钩子）挂在 show() 上就会扑空，GUI 永远退不出来
    window.show()
    # 打开即最大化：见模块顶部 START_MAXIMIZED 的说明
    if START_MAXIMIZED:
        window.showMaximized()

    # 可选：命令行直接打开数据库，便于脚本化启动
    for arg in argv[1:]:
        if arg.lower().endswith((".tdb", ".dat")) and Path(arg).exists():
            window.load_database(Path(arg))
            break

    return app.exec()


__all__ = ["main", "setup_logging", "START_MAXIMIZED"]


if __name__ == "__main__":
    # 直接运行本文件（python pycalphad_gui/app.py）时的入口。
    #
    # 此时 __package__ 是 ''，main() 里的相对导入会报
    # "attempted relative import with no known parent package"。
    # 补上 sys.path 并把 __package__ 设成包名后，那些相对导入就能正常解析。
    import sys
    from pathlib import Path

    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        __package__ = "pycalphad_gui"  # noqa: A001 - 模块级赋值，故意的
    raise SystemExit(main())

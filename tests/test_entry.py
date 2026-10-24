"""启动入口回归测试：三条启动路径都要能起界面。

``python app.py``、``python -m pycalphad_gui``、``python path/to/__main__.py``
在 PyQt6 下走的是两套不同的导入机制（脚本模式 ``__main__.__spec__`` 为 ``None``、
``__package__`` 为 ``''``，相对导入会被 importlib 直接拒绝）。一旦改动入口文件
很容易只跑通一条 —— 历史上就是因为只支持前两条，直接敲 ``__main__.py`` 路径会
报 ``ImportError: attempted relative import with no known parent package`` ——
因此在这里三条一起锁死。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent          # pycalphad_gui/
PKG_DIR = ROOT / "pycalphad_gui"                       # app.py 所在目录
APP_PY = PKG_DIR / "app.py"
MAIN_PY = PKG_DIR / "__main__.py"
BIN_PY = sys.executable


def _report(results: List[Tuple[str, bool, str]]) -> int:
    failed = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail and not ok else ""))
        failed += 0 if ok else 1
    print(f"\n通过 {len(results) - failed}/{len(results)}")
    return failed


def _run_entry_file(entry: Path) -> Tuple[bool, str]:
    """在独立解释器里以脚本模式执行某个入口文件。

    不能在本进程里 ``runpy.run_path``：pytest-qt 已经建了一个 ``QApplication``，
    再让入口文件建第二个，Qt 会直接 abort，整个 pytest 进程跟着陪葬。子进程
    里由包装脚本给 ``MainWindow.show`` 挂钩子，2 秒后退出主循环，避免被 GUI
    挂死；这样测的仍是真实的脚本模式导入路径。
    """
    wrapper = (
        "import runpy, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from PyQt6.QtCore import QTimer\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "from pycalphad_gui.ui.main_window import MainWindow\n"
        "orig_show = MainWindow.show\n"
        "def patched_show(self):\n"
        "    QTimer.singleShot(2000, QApplication.instance().quit)\n"
        "    orig_show(self)\n"
        "MainWindow.show = patched_show\n"
        "try:\n"
        "    runpy.run_path(sys.argv[2], run_name='__main__')\n"
        "except SystemExit as exc:\n"
        "    code = exc.code or 0\n"
        "else:\n"
        "    code = 0\n"
        "finally:\n"
        "    MainWindow.show = orig_show\n"
        "sys.exit(code)\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.run(
        [BIN_PY, "-c", wrapper, str(ROOT), str(entry)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )
    if proc.returncode != 0:
        out = (proc.stdout or "") + (proc.stderr or "")
        return False, f"退出码 {proc.returncode}\n{out[-1500:]}"
    return True, ""


def _check_run_as_script() -> Tuple[bool, str]:
    """以脚本模式执行 app.py（等价于 ``python pycalphad_gui/app.py``）。"""
    return _run_entry_file(APP_PY)


def _check_run_main_file_directly() -> Tuple[bool, str]:
    """把 ``__main__.py`` 的文件路径直接交给解释器（新手最常敲的写法）。"""
    return _run_entry_file(MAIN_PY)


def _check_run_as_module() -> Tuple[bool, str]:
    """``python -m pycalphad_gui``：真实起进程，确认不会启动即退出。"""
    proc = subprocess.Popen(
        [BIN_PY, "-m", "pycalphad_gui"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        # GUI 是阻塞式事件循环，正常情况会一直活着；只有启动失败才会很快退出
        time.sleep(8)
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            return False, f"进程在 8 秒内自行退出\n{out[-1500:]}"
        proc.terminate()
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
    return True, ""


def test_run_as_script() -> None:
    ok, detail = _check_run_as_script()
    assert ok, detail


def test_run_main_file_directly() -> None:
    ok, detail = _check_run_main_file_directly()
    assert ok, detail


def test_run_as_module() -> None:
    ok, detail = _check_run_as_module()
    assert ok, detail


def main() -> int:
    print(f"解释器: {BIN_PY}")
    print(f"工作目录: {ROOT}\n")

    results = [
        ("脚本模式 python app.py", *_check_run_as_script()),
        ("脚本模式 python __main__.py", *_check_run_main_file_directly()),
        ("包模式 python -m pycalphad_gui", *_check_run_as_module()),
    ]
    return _report(results)


if __name__ == "__main__":
    raise SystemExit(main())

"""启动入口。

三条运行方式都能起界面，它们走的是两套不同的导入机制：

* ``python -m pycalphad_gui``        —— 包模式，``__package__`` 非空，相对导入可用
* ``python pycalphad_gui/app.py``    —— 脚本模式（见 :mod:`pycalphad_gui.app`）
* ``python pycalphad_gui/__main__.py`` —— 直接把本文件路径交给解释器

最后一种是新手最常敲的写法：此时 ``__package__`` 为 ``''``（不是包名），
importlib 的 sanity check 会拒绝 ``from .app import main``，报
``ImportError: attempted relative import with no known parent package``。
所以这里和 :mod:`pycalphad_gui.app` 一样做 ``sys.path`` 补位 + 绝对导入回退。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 以文件路径直接运行时，sys.path[0] 是本文件所在目录（包内部），
# 包本体在上一级，必须补进去才能做绝对导入。
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # 包模式：python -m pycalphad_gui
    from .app import main
except ImportError:  # 脚本模式：python path/to/__main__.py
    from pycalphad_gui.app import main

if __name__ == "__main__":
    # 注意：包模式下 `python -m pycalphad_gui` 时本文件就是 __main__，会走到这里；
    # 脚本模式下由 app.py 的尾部守卫负责调用。两条路径都不要删这个 SystemExit。
    raise SystemExit(main())

__all__ = ["main"]

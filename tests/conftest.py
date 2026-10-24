# -*- coding: utf-8 -*-
"""pytest 收集配置。

``tests/third_party/`` 存放 pycalphad / espei / scheil 官方源码包里的测试
（仅作离线参考与上游回归用，依赖各自包的私有 fixture），默认不参与本项目
``pytest`` 收集；需要跑的时候在该目录下单独执行 ``pytest tests/third_party/<pkg>``。
"""
import os

import pytest

collect_ignore_glob = ["third_party/*"]

# 必须在任何 Qt 模块 import 之前定下来
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """整个会话共用同一个 QApplication。

    pytest-qt 只有在测试显式请求 ``qapp`` / ``qtbot`` 时才建应用，而本仓库的
    离屏冒烟测试直接 ``DiagramPanel()`` / ``MainWindow()``。单独跑某个测试
    （``pytest -k xxx``）时就会在没应用的情况下构造 QWidget，Qt 直接 abort，
    连 traceback 都没有 —— 加上这个 fixture 后，整份跑和单跑行为一致。
    """
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app

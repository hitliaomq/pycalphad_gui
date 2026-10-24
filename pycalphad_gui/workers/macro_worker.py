"""宏命令的后台执行器。

宏里的每个计算命令（DIAGRAM / PROPERTY / SCHEIL / ESPEI / HT）都可能跑上
几十秒，因此整份宏统一丢进线程池；执行过程中通过信号把日志、图像、数据库
和表格送回主线程。

``BaseWorker`` 已提供进度 / 成功 / 失败 / 取消四条标准信号，这里额外补上
宏特有的日志、结果图、数据库、元素选择与表格五条通道。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Sequence

from PyQt6.QtCore import pyqtSignal

from ..core.macro_engine import MacroCallbacks, MacroSession, run_macro_text
from .base_worker import BaseWorker, WorkerSignals


class MacroWorkerSignals(WorkerSignals):
    """宏执行器对外信号。"""

    #: 一行日志（已带行号 / 命令原文）
    log = pyqtSignal(str)
    #: 当前步骤的简短状态
    status = pyqtSignal(str)
    #: (figure, axes 列表, 图注)
    figure = pyqtSignal(object, object, str)
    #: 宏切换了数据库（绝对路径）
    database = pyqtSignal(str)
    #: (元素, 相) 选择变化
    selection = pyqtSignal(list, list)
    #: (DataFrame, 标题)
    table = pyqtSignal(object, str)


def _run_macro(
    text: str,
    base_dir: str,
    signals: MacroWorkerSignals,
    database_path: Optional[str],
    elements: Sequence[str],
    phases: Sequence[str],
    should_cancel=None,
):
    callbacks = MacroCallbacks(
        log=signals.log.emit,
        status=signals.status.emit,
        progress=signals.progress.emit,
        figure=signals.figure.emit,
        database=signals.database.emit,
        selection=signals.selection.emit,
        table=signals.table.emit,
        should_cancel=should_cancel,
    )
    return run_macro_text(
        text,
        base_dir=Path(base_dir) if base_dir else None,
        callbacks=callbacks,
        initial_database=database_path,
        initial_elements=list(elements),
        initial_phases=list(phases),
    )


def _run_macro_session_line(
    session: MacroSession,
    text: str,
    signals: MacroWorkerSignals,
    should_cancel=None,
):
    callbacks = MacroCallbacks(
        log=signals.log.emit,
        status=signals.status.emit,
        progress=signals.progress.emit,
        figure=signals.figure.emit,
        database=signals.database.emit,
        selection=signals.selection.emit,
        table=signals.table.emit,
        should_cancel=should_cancel,
    )
    # 会话对象跨步骤存活，每步换成本次 worker 的信号出口
    session.set_callbacks(callbacks)
    return session.run_line(text)


class MacroWorker(BaseWorker):
    """把一份宏文本包装成可取消的后台任务。"""

    def __init__(
        self,
        text: str,
        base_dir: Optional[Path] = None,
        database_path: Optional[str] = None,
        elements: Optional[Sequence[str]] = None,
        phases: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(_run_macro, cancellable=True)
        self.signals = MacroWorkerSignals()
        self.args = (
            text,
            str(base_dir) if base_dir is not None else "",
            self.signals,
            database_path,
            list(elements or []),
            list(phases or []),
        )
        self.context = "宏"


class MacroCommandWorker(BaseWorker):
    """把交互式会话的一条命令包装成可取消的后台任务。"""

    def __init__(self, session: MacroSession, text: str) -> None:
        super().__init__(_run_macro_session_line, cancellable=True)
        self.signals = MacroWorkerSignals()
        self.args = (session, text, self.signals)
        self.context = "宏"


__all__ = ["MacroWorker", "MacroCommandWorker", "MacroWorkerSignals"]

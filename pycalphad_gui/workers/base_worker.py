"""后台计算任务基类。

pycalphad 的单次计算动辄十余秒（实测 ``binplot`` ≈ 12 s、``ternplot`` ≈ 15 s），
必须丢进线程池，否则界面直接冻结。本模块提供：

* 统一的信号契约（进度 / 成功 / 失败 / 取消）；
* 取消令牌——任务在每个可中断点自行查询，不依赖抢占式中断；
* 异常的集中翻译，UI 只收到面向用户的文本。
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from ..core.diagnostics import CalculationError, diagnose, log_exception

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """后台任务对外发出的信号，只能在主线程槽函数中消费。"""

    #: (已完成, 总数, 提示文本)
    progress = pyqtSignal(int, int, str)
    #: 计算成功，携带结果对象
    succeeded = pyqtSignal(object)
    #: 计算失败，携带 (用户可读信息, 技术细节)
    failed = pyqtSignal(str, str)
    #: 被用户取消
    cancelled = pyqtSignal()


class CancelToken:
    """线程安全的取消令牌。

    pycalphad 内部没有中断点，因此取消只能在任务自身的检查点生效：
    任务每隔若干迭代调用 :meth:`is_set`，一旦为真便立即返回。
    """

    __slots__ = ("_value",)

    def __init__(self) -> None:
        self._value = False

    def set(self) -> None:
        self._value = True

    def is_set(self) -> bool:
        return self._value

    def raise_if_set(self) -> None:
        if self._value:
            raise _Cancelled()


class _Cancelled(Exception):
    """内部取消信号，不对外暴露。"""


class BaseWorker(QRunnable):
    """把任意计算函数包装成可取消、可上报进度的 QRunnable。

    Parameters
    ----------
    func
        计算函数。若签名里含 ``progress`` / ``should_cancel`` 关键字，
        会自动注入回调；否则按普通函数执行。
    *args, **kwargs
        透传给 ``func``。
    cancellable
        是否支持取消（默认 True）。
    """

    def __init__(
        self,
        func: Callable[..., Any],
        *args: Any,
        cancellable: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.cancellable = cancellable
        self.signals = WorkerSignals()
        self._token = CancelToken()
        self.setAutoDelete(True)

    # ---------------------------------------------------------------- 控制
    @property
    def token(self) -> CancelToken:
        return self._token

    def cancel(self) -> None:
        if not self.cancellable:
            return
        self._token.set()

    @property
    def is_cancelled(self) -> bool:
        return self._token.is_set()

    # ---------------------------------------------------------------- 执行
    def run(self) -> None:
        """线程入口。异常在此收敛，绝不向线程外抛出。"""
        kwargs = dict(self.kwargs)
        try:
            params = inspect.signature(self.func).parameters
        except (TypeError, ValueError):  # pragma: no cover - 内建函数
            params = {}

        if "progress" in params:
            kwargs["progress"] = self._make_progress()
        if "should_cancel" in params and self.cancellable:
            kwargs["should_cancel"] = self._token.is_set

        try:
            result = self.func(*self.args, **kwargs)
        except _Cancelled:
            logger.info("任务已取消")
            self.signals.cancelled.emit()
            return
        except CalculationError as exc:
            log_exception(exc, getattr(self, "context", "后台任务"))
            self.signals.failed.emit(exc.user_message, exc.detail)
            return
        except Exception as exc:  # noqa: BLE001 - 边界处统一翻译
            log_exception(exc, getattr(self, "context", "后台任务"))
            translated = diagnose(exc, getattr(self, "context", "计算"))
            self.signals.failed.emit(translated.user_message, translated.detail)
            return

        self.signals.succeeded.emit(result)

    # ---------------------------------------------------------------- 内部
    def _make_progress(self) -> Callable[[int, int, str], None]:
        """构造进度回调；回调自身的异常绝不影响计算。"""

        def _cb(current: int, total: int, message: str = "") -> None:
            try:
                self.signals.progress.emit(int(current), int(total), message)
            except Exception:  # pragma: no cover
                pass

        return _cb

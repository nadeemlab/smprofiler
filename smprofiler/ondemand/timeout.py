"""General-purpose one-time timeout functionality based on Unix signal alarm."""
from typing import Callable
import signal

from smprofiler.standalone_utilities.log_formats import colorized_logger

logger = colorized_logger(__name__)


class SMProfilerTimeoutError(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class TimeoutHandler:
    active: bool
    callback: Callable
    timeout: int

    def __init__(self, callback: Callable, timeout: int):
        self.active = True
        self.callback = callback
        self.timeout = timeout

    def handle(self, signum, frame) -> None:
        if self.active:
            message = f'Waited {self.timeout} seconds, timed out.'
            logger.error(message)
            self.callback(self.timeout)
            raise SMProfilerTimeoutError(message)

    def disalarm(self) -> None:
        self.active = False


def create_timeout_handler(callback: Callable, timeout_seconds: int) -> TimeoutHandler:
    handler = TimeoutHandler(callback, timeout_seconds)
    signal.signal(signal.SIGALRM, handler.handle)
    signal.alarm(timeout_seconds)
    return handler

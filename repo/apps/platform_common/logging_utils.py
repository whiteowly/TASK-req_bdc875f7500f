"""Logging filter that injects the per-request id."""
import logging
import threading

_local = threading.local()


def set_request_id(value: str) -> None:
    _local.request_id = value


def get_request_id() -> str:
    return getattr(_local, "request_id", "-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
        record.request_id = get_request_id()
        return True

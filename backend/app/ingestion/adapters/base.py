from typing import Protocol

from app.contracts import CanonicalEvent


class AdapterError(ValueError):
    def __init__(self, reason_code: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code


class SourceAdapter(Protocol):
    source_name: str
    def adapt(self, raw: dict) -> CanonicalEvent: ...

"""Single source of truth for user confirmation decisions."""

from dataclasses import dataclass
from enum import Enum
import threading
import time
from typing import Any, Callable


class ConfirmationStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ConfirmationRequest:
    confirmation_id: str
    task_id: str
    tool: str
    explanation: str
    risk: str
    parameters: dict[str, Any]
    created_at: float
    expires_at: float
    status: ConfirmationStatus = ConfirmationStatus.PENDING


class ConfirmationManager:
    def __init__(self, timeout_seconds: float = 120.0):
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._lock = threading.RLock()
        self._pending: dict[str, ConfirmationRequest] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._listeners: list[Callable[[ConfirmationRequest], None]] = []

    def add_listener(self, listener: Callable[[ConfirmationRequest], None]) -> None:
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[ConfirmationRequest], None]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def request(
        self,
        task_id: str,
        tool: str,
        explanation: str,
        risk: str,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> ConfirmationRequest:
        with self._lock:
            existing = self._pending.get(task_id)
            if existing and existing.status == ConfirmationStatus.PENDING:
                return existing

            now = time.time()
            timeout = max(1.0, float(timeout_seconds or self.timeout_seconds))
            request = ConfirmationRequest(
                confirmation_id=f"confirm-{task_id}-{int(now * 1000)}",
                task_id=str(task_id),
                tool=str(tool),
                explanation=str(explanation),
                risk=str(risk),
                parameters=_safe_parameters(parameters or {}),
                created_at=now,
                expires_at=now + timeout,
            )
            self._pending[request.task_id] = request
            timer = threading.Timer(timeout, self.expire, args=(request.task_id,))
            timer.daemon = True
            self._timers[request.task_id] = timer
            timer.start()
            listeners = list(self._listeners)

        for listener in listeners:
            try:
                listener(request)
            except Exception:
                pass
        return request

    def get(self, task_id: str) -> ConfirmationRequest | None:
        with self._lock:
            return self._pending.get(str(task_id))

    def pending(self) -> list[ConfirmationRequest]:
        with self._lock:
            return [item for item in self._pending.values() if item.status == ConfirmationStatus.PENDING]

    def resolve(self, task_id: str, approved: bool) -> ConfirmationRequest | None:
        status = ConfirmationStatus.APPROVED if approved else ConfirmationStatus.DENIED
        return self._resolve(task_id, status)

    def cancel(self, task_id: str) -> ConfirmationRequest | None:
        return self._resolve(task_id, ConfirmationStatus.CANCELLED)

    def expire(self, task_id: str) -> ConfirmationRequest | None:
        return self._resolve(task_id, ConfirmationStatus.EXPIRED)

    def _resolve(self, task_id: str, status: ConfirmationStatus) -> ConfirmationRequest | None:
        with self._lock:
            current = self._pending.get(str(task_id))
            if not current or current.status != ConfirmationStatus.PENDING:
                return current
            resolved = ConfirmationRequest(**{**current.__dict__, "status": status})
            self._pending[resolved.task_id] = resolved
            timer = self._timers.pop(resolved.task_id, None)
            if timer:
                timer.cancel()
            listeners = list(self._listeners)

        for listener in listeners:
            try:
                listener(resolved)
            except Exception:
                pass
        return resolved


def _safe_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    hidden = {"password", "token", "secret", "api_key", "access_token", "authorization"}
    result = {}
    for key, value in parameters.items():
        key_text = str(key).lower()
        if any(part in key_text for part in hidden):
            result[str(key)] = "[redacted]"
        elif key_text in {"content", "body", "message_text"} and len(str(value)) > 240:
            result[str(key)] = f"{str(value)[:240]}..."
        else:
            result[str(key)] = value
    return result
"""固定期限の匿名セッション。解析済みJSONだけを容量制限付きでメモリ保持する。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import hashlib
import hmac
import json
import math
import os
import re
import secrets
from threading import RLock
from time import monotonic
from typing import Callable, Mapping


TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


class SessionError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SessionSettings:
    ttl_seconds: int = 20 * 60
    max_sessions: int = 1000
    cleanup_interval_seconds: int = 30
    max_data_bytes: int = 8 * 1024 * 1024
    total_data_bytes: int = 64 * 1024 * 1024

    def __post_init__(self) -> None:
        for value in (self.ttl_seconds, self.max_sessions, self.cleanup_interval_seconds,
                      self.max_data_bytes, self.total_data_bytes):
            if type(value) is not int or value < 1:
                raise ValueError("セッション設定には正の整数を指定してください")
        if self.max_data_bytes > self.total_data_bytes:
            raise ValueError("セッション全体の容量は1セッションの容量以上にしてください")

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> SessionSettings:
        values = os.environ if environ is None else environ

        def positive(name: str, default: int) -> int:
            value = values.get(name, str(default))
            if not value.isascii() or not value.isdigit() or int(value) < 1:
                raise ValueError(name + "には正の整数を指定してください")
            return int(value)

        return cls(ttl_seconds=positive("SESSION_TTL_SECONDS", 1200),
                   max_sessions=positive("SESSION_MAX_COUNT", 1000),
                   max_data_bytes=positive("SESSION_MAX_BYTES", 8 * 1024 * 1024),
                   total_data_bytes=positive("SESSION_TOTAL_BYTES", 64 * 1024 * 1024))


@dataclass(frozen=True)
class _Session:
    created_at: float
    csrf_token: str
    revision: int = 0
    report_json: bytes | None = None
    timetable_json: bytes | None = None

    @property
    def data_size(self) -> int:
        return len(self.report_json or b"") + len(self.timetable_json or b"")


class SessionStore:
    """Cookie原文を保存せず、そのSHA-256をキーにする。操作で期限を延ばさない。"""

    def __init__(self, settings: SessionSettings | None = None, *,
                 clock: Callable[[], float] = monotonic,
                 token_factory: Callable[[], str] | None = None) -> None:
        self.settings = settings or SessionSettings()
        self._clock = clock
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._records: dict[str, _Session] = {}
        self._stored_bytes = 0
        self._lock = RLock()

    @staticmethod
    def _key(token: str | None) -> str | None:
        if not isinstance(token, str) or TOKEN_PATTERN.fullmatch(token) is None:
            return None
        return hashlib.sha256(token.encode("ascii")).hexdigest()

    def _purge(self, now: float) -> int:
        expired = [key for key, value in self._records.items()
                   if now >= value.created_at + self.settings.ttl_seconds]
        for key in expired:
            self._remove(key)
        return len(expired)

    def _remove(self, key: str) -> None:
        self._stored_bytes -= self._records.pop(key).data_size

    def _record(self, token: str | None) -> tuple[str, _Session, float]:
        now = self._clock()
        self._purge(now)
        key = self._key(token)
        if key not in self._records:
            raise SessionError(401, "session_required", "セッションがないか、有効期限が切れています。新しく開始してください。")
        return key, self._records[key], now

    @staticmethod
    def _check_update(session: _Session, csrf_token: str | None, revision: int) -> None:
        if (not isinstance(csrf_token, str) or TOKEN_PATTERN.fullmatch(csrf_token) is None
                or not hmac.compare_digest(session.csrf_token, csrf_token)):
            raise SessionError(403, "invalid_csrf_token", "操作の確認情報が一致しません。セッションを取得し直してください。")
        if type(revision) is not int or revision < 0:
            raise SessionError(422, "invalid_session_revision", "セッションの更新番号を正しく指定してください。")
        if session.revision != revision:
            raise SessionError(409, "session_revision_conflict", "別の操作で情報が更新されました。最新の状態を取得してからやり直してください。")

    def _workspace(self, session: _Session, now: float) -> dict:
        return {"schema_version": 1, "revision": session.revision, "session": self._view(session, now),
                "report": json.loads(session.report_json) if session.report_json is not None else None,
                "timetable": json.loads(session.timetable_json) if session.timetable_json is not None else None}

    def _view(self, session: _Session, now: float) -> dict:
        return {"schema_version": 1, "status": "active", "csrf_token": session.csrf_token,
                "ttl_seconds": self.settings.ttl_seconds,
                "expires_in_seconds": math.ceil(session.created_at + self.settings.ttl_seconds - now)}

    def create_or_resume(self, token: str | None) -> tuple[str | None, dict]:
        """有効なCookieなら同じセッションを返す。新規作成時だけCookie値も返す。"""
        with self._lock:
            now = self._clock()
            self._purge(now)
            key = self._key(token)
            if key in self._records:
                return None, self._view(self._records[key], now)
            if len(self._records) >= self.settings.max_sessions:
                raise SessionError(503, "session_capacity_exceeded", "セッション数が上限に達しています。時間をおいて再試行してください。")
            # クライアントが指定した未知の識別子は採用しない。
            for _ in range(3):
                new_token = self._token_factory()
                new_key = self._key(new_token)
                if new_key is not None and new_key not in self._records:
                    break
            else:
                raise SessionError(503, "session_unavailable", "セッションを作成できません。時間をおいて再試行してください。")
            session = _Session(now, self._token_factory())
            self._records[new_key] = session
            return new_token, self._view(session, now)

    def get(self, token: str | None) -> dict:
        with self._lock:
            _, session, now = self._record(token)
            return self._view(session, now)

    def workspace(self, token: str | None) -> dict:
        with self._lock:
            _, session, now = self._record(token)
            return self._workspace(session, now)

    def checked_workspace(self, token: str | None, csrf_token: str | None, revision: int) -> dict:
        with self._lock:
            _, session, now = self._record(token)
            self._check_update(session, csrf_token, revision)
            return self._workspace(session, now)

    def assert_current(self, token: str | None, csrf_token: str | None, revision: int) -> None:
        with self._lock:
            _, session, _ = self._record(token)
            self._check_update(session, csrf_token, revision)

    def begin_update(self, token: str | None, csrf_token: str | None, revision: int, kind: str) -> int:
        """旧結果を先に破棄する。後続の失敗や遅延応答で旧結果を復活させない。"""
        if kind not in {"report", "timetable"}:
            raise ValueError("未知のセッション項目です")
        with self._lock:
            key, session, _ = self._record(token)
            self._check_update(session, csrf_token, revision)
            updated = replace(session, **{kind + "_json": None, "revision": session.revision + 1})
            self._stored_bytes += updated.data_size - session.data_size
            self._records[key] = updated
            return updated.revision

    def commit(self, token: str | None, csrf_token: str | None, revision: int, kind: str, data: dict) -> dict:
        if kind not in {"report", "timetable"}:
            raise ValueError("未知のセッション項目です")
        payload = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        with self._lock:
            key, session, now = self._record(token)
            self._check_update(session, csrf_token, revision)
            updated = replace(session, **{kind + "_json": payload, "revision": session.revision + 1})
            if updated.data_size > self.settings.max_data_bytes:
                raise SessionError(413, "session_data_too_large", "解析結果が一時保持できる容量を超えています。")
            total = self._stored_bytes + updated.data_size - session.data_size
            if total > self.settings.total_data_bytes:
                raise SessionError(503, "session_memory_full", "一時保持用のメモリが上限に達しています。時間をおいて再試行してください。")
            self._records[key] = updated
            self._stored_bytes = total
            return self._workspace(updated, now)

    def end(self, token: str | None, csrf_token: str | None) -> None:
        with self._lock:
            view = self.get(token)
            if (not isinstance(csrf_token, str) or TOKEN_PATTERN.fullmatch(csrf_token) is None
                    or not hmac.compare_digest(view["csrf_token"], csrf_token)):
                raise SessionError(403, "invalid_csrf_token", "操作の確認情報が一致しません。セッションを取得し直してください。")
            self._remove(self._key(token))

    def cleanup(self) -> int:
        with self._lock:
            return self._purge(self._clock())

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._stored_bytes = 0

    async def cleanup_loop(self) -> None:
        interval = min(self.settings.cleanup_interval_seconds, self.settings.ttl_seconds)
        while True:
            await asyncio.sleep(interval)
            self.cleanup()

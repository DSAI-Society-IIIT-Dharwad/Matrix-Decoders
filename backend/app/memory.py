from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, List, Optional, Set

from .config import settings
from .logger import get_logger

log = get_logger("memory")


def _normalize_languages(languages: Optional[Iterable[str]]) -> list[str]:
    normalized = sorted(
        {
            str(language).strip()
            for language in (languages or [])
            if str(language).strip() and str(language).strip() != "unknown"
        }
    )
    return normalized


def _safe_json_loads(raw_value: str, fallback):
    try:
        return json.loads(raw_value or "")
    except json.JSONDecodeError:
        return fallback


class PersistentStore:
    """SQLite-backed session store for chat history, transcripts, and telemetry."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    languages_json TEXT NOT NULL DEFAULT '[]',
                    selected_language TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                ON messages(session_id, id);

                CREATE TABLE IF NOT EXISTS transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    source TEXT NOT NULL,
                    text TEXT NOT NULL,
                    dominant_language TEXT NOT NULL DEFAULT '',
                    languages_json TEXT NOT NULL DEFAULT '[]',
                    is_code_mixed INTEGER NOT NULL DEFAULT 0,
                    segments_json TEXT NOT NULL DEFAULT '[]',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_transcripts_session_id
                ON transcripts(session_id, id);

                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT '',
                    latency_ms REAL,
                    error_message TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_telemetry_session_id
                ON telemetry(session_id, id);
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _ensure_session(self, session_id: Optional[str]) -> None:
        if not session_id:
            return

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO sessions(session_id)
                VALUES (?)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                """,
                (session_id,),
            )

    def _touch_session(self, session_id: Optional[str]) -> None:
        if not session_id:
            return

        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,),
            )

    def add(self, session_id: str, role: str, text: str) -> None:
        """Add a message to the persisted session history."""
        self._ensure_session(session_id)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO messages(session_id, role, content)
                VALUES (?, ?, ?)
                """,
                (session_id, role, text),
            )
            self._conn.execute(
                "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (session_id,),
            )
        log.debug(f"Session '{session_id}' [{role}]: {text[:60]}...")

    def get(self, session_id: str) -> list:
        """Get the most recent messages for a session (configurable window)."""
        max_msgs = settings.max_context_messages
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, max_msgs),
            ).fetchall()

        history = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
        return history

    def track_languages(self, session_id: str, languages: Set[str]) -> None:
        """Track which languages have been used in a session."""
        self._ensure_session(session_id)
        existing = self.get_languages(session_id)
        merged = _normalize_languages(existing.union(languages))
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE sessions
                SET languages_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (json.dumps(merged), session_id),
            )

    def get_languages(self, session_id: str) -> Set[str]:
        """Get all languages detected in the session so far."""
        with self._lock:
            row = self._conn.execute(
                "SELECT languages_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        if not row:
            return set()

        try:
            stored_languages = json.loads(row["languages_json"] or "[]")
        except json.JSONDecodeError:
            return set()

        return set(_normalize_languages(stored_languages))

    def set_selected_language(self, session_id: str, language: Optional[str]) -> None:
        if not session_id or not language:
            return

        self._ensure_session(session_id)
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE sessions
                SET selected_language = ?, updated_at = CURRENT_TIMESTAMP
                WHERE session_id = ?
                """,
                (language, session_id),
            )

    def record_transcript(
        self,
        session_id: Optional[str],
        source: str,
        text: str,
        dominant_language: Optional[str],
        languages: Optional[Iterable[str]],
        is_code_mixed: bool,
        segments: Optional[list],
        details: Optional[dict] = None,
    ) -> None:
        if session_id:
            self._ensure_session(session_id)
            normalized_languages = set(_normalize_languages(languages))
            if normalized_languages:
                self.track_languages(session_id, normalized_languages)
            if dominant_language:
                self.set_selected_language(session_id, dominant_language)
        else:
            normalized_languages = set(_normalize_languages(languages))

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO transcripts(
                    session_id,
                    source,
                    text,
                    dominant_language,
                    languages_json,
                    is_code_mixed,
                    segments_json,
                    details_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    source,
                    text,
                    dominant_language or "",
                    json.dumps(sorted(normalized_languages)),
                    int(bool(is_code_mixed)),
                    json.dumps(segments or []),
                    json.dumps(details or {}),
                ),
            )

        self._touch_session(session_id)

    def record_latency(
        self,
        session_id: Optional[str],
        name: str,
        latency_ms: float,
        status: str = "ok",
        details: Optional[dict] = None,
    ) -> None:
        if session_id:
            self._ensure_session(session_id)

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO telemetry(
                    session_id,
                    kind,
                    name,
                    status,
                    latency_ms,
                    details_json
                )
                VALUES (?, 'latency', ?, ?, ?, ?)
                """,
                (
                    session_id,
                    name,
                    status,
                    float(latency_ms),
                    json.dumps(details or {}),
                ),
            )

        self._touch_session(session_id)

    def record_error(
        self,
        session_id: Optional[str],
        name: str,
        error_message: str,
        details: Optional[dict] = None,
    ) -> None:
        if session_id:
            self._ensure_session(session_id)

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO telemetry(
                    session_id,
                    kind,
                    name,
                    status,
                    error_message,
                    details_json
                )
                VALUES (?, 'error', ?, 'error', ?, ?)
                """,
                (
                    session_id,
                    name,
                    error_message,
                    json.dumps(details or {}),
                ),
            )

        self._touch_session(session_id)

    def clear(self, session_id: str) -> None:
        """Clear all persisted history for a session."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        log.info(f"Cleared session '{session_id}'")

    def list_session_summaries(self) -> List[dict]:
        """Return session summaries for dashboard and history views."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    s.session_id,
                    s.created_at,
                    s.updated_at,
                    s.languages_json,
                    s.selected_language,
                    (
                        SELECT COUNT(*)
                        FROM messages m
                        WHERE m.session_id = s.session_id
                    ) AS message_count,
                    (
                        SELECT COUNT(*)
                        FROM transcripts t
                        WHERE t.session_id = s.session_id
                    ) AS transcript_count,
                    (
                        SELECT COUNT(*)
                        FROM telemetry y
                        WHERE y.session_id = s.session_id
                    ) AS telemetry_count,
                    (
                        SELECT content
                        FROM messages m
                        WHERE m.session_id = s.session_id
                        ORDER BY m.id DESC
                        LIMIT 1
                    ) AS last_message,
                    (
                        SELECT text
                        FROM transcripts t
                        WHERE t.session_id = s.session_id
                        ORDER BY t.id DESC
                        LIMIT 1
                    ) AS last_transcript
                FROM sessions s
                ORDER BY s.updated_at DESC, s.session_id ASC
                """
            ).fetchall()

        summaries: list[dict] = []
        for row in rows:
            summaries.append(
                {
                    "session_id": str(row["session_id"]),
                    "created_at": str(row["created_at"]),
                    "updated_at": str(row["updated_at"]),
                    "languages": _normalize_languages(_safe_json_loads(row["languages_json"], [])),
                    "selected_language": str(row["selected_language"] or ""),
                    "message_count": int(row["message_count"] or 0),
                    "transcript_count": int(row["transcript_count"] or 0),
                    "telemetry_count": int(row["telemetry_count"] or 0),
                    "last_message": str(row["last_message"] or ""),
                    "last_transcript": str(row["last_transcript"] or ""),
                }
            )

        return summaries

    def list_sessions(self) -> List[str]:
        """List all active session IDs."""
        return [summary["session_id"] for summary in self.list_session_summaries()]

    def get_session_snapshot(self, session_id: str) -> Optional[dict]:
        """Return a full persisted snapshot for one session."""
        with self._lock:
            session_row = self._conn.execute(
                """
                SELECT session_id, created_at, updated_at, languages_json, selected_language
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

            if not session_row:
                return None

            message_rows = self._conn.execute(
                """
                SELECT id, role, content, created_at
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

            transcript_rows = self._conn.execute(
                """
                SELECT
                    id,
                    source,
                    text,
                    dominant_language,
                    languages_json,
                    is_code_mixed,
                    segments_json,
                    details_json,
                    created_at
                FROM transcripts
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

            telemetry_rows = self._conn.execute(
                """
                SELECT
                    id,
                    kind,
                    name,
                    status,
                    latency_ms,
                    error_message,
                    details_json,
                    created_at
                FROM telemetry
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

        messages = [
            {
                "id": int(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "created_at": str(row["created_at"]),
            }
            for row in message_rows
        ]

        transcripts = [
            {
                "id": int(row["id"]),
                "source": str(row["source"]),
                "text": str(row["text"]),
                "dominant_language": str(row["dominant_language"] or ""),
                "languages": _normalize_languages(_safe_json_loads(row["languages_json"], [])),
                "is_code_mixed": bool(row["is_code_mixed"]),
                "segments": _safe_json_loads(row["segments_json"], []),
                "details": _safe_json_loads(row["details_json"], {}),
                "created_at": str(row["created_at"]),
            }
            for row in transcript_rows
        ]

        telemetry = [
            {
                "id": int(row["id"]),
                "kind": str(row["kind"]),
                "name": str(row["name"]),
                "status": str(row["status"] or ""),
                "latency_ms": float(row["latency_ms"]) if row["latency_ms"] is not None else None,
                "error_message": str(row["error_message"] or ""),
                "details": _safe_json_loads(row["details_json"], {}),
                "created_at": str(row["created_at"]),
            }
            for row in telemetry_rows
        ]

        return {
            "session_id": str(session_row["session_id"]),
            "created_at": str(session_row["created_at"]),
            "updated_at": str(session_row["updated_at"]),
            "languages": _normalize_languages(_safe_json_loads(session_row["languages_json"], [])),
            "selected_language": str(session_row["selected_language"] or ""),
            "message_count": len(messages),
            "transcript_count": len(transcripts),
            "telemetry_count": len(telemetry),
            "messages": messages,
            "transcripts": transcripts,
            "telemetry": telemetry,
        }

    def session_count(self) -> int:
        """Return the number of active sessions."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()
        return int(row["count"]) if row else 0


store = PersistentStore(settings.persistence_db_path)

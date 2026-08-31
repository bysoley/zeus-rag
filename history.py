"""SQLite-backed conversation history for the local assistant."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_TITLE = "새 대화"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def make_title(message: str, max_length: int = 40) -> str:
    normalized = re.sub(r"\s+", " ", message).strip()
    if not normalized:
        return DEFAULT_TITLE
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "…"


def build_retrieval_query(
    current_message: str,
    previous_messages: list[dict[str, Any]],
    history_turns: int = 2,
    max_chars: int = 4000,
) -> str:
    previous_user = [
        str(message["content"])
        for message in previous_messages
        if message.get("role") == "user" and message.get("status") == "complete"
    ]
    parts = previous_user[-history_turns:] + [current_message]
    return "\n".join(parts)[-max_chars:]


def select_chat_history(
    messages: list[dict[str, Any]], max_turns: int = 6, max_chars: int = 12000
) -> list[dict[str, str]]:
    eligible = [
        {"role": str(message["role"]), "content": str(message["content"])}
        for message in messages
        if message.get("role") in {"user", "assistant"}
        and message.get("status") == "complete"
        and message.get("content")
    ][-(max_turns * 2) :]

    while eligible and sum(len(message["content"]) for message in eligible) > max_chars:
        if len(eligible) == 1:
            eligible[0]["content"] = eligible[0]["content"][-max_chars:]
            break
        eligible.pop(0)
    return eligible


class HistoryStore:
    def __init__(self, path: Path):
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, SCHEMA_VERSION}:
                raise RuntimeError(
                    f"지원하지 않는 대화 DB 스키마 버전입니다: {version}"
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL DEFAULT '',
                    scope TEXT,
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL CHECK (
                        status IN ('streaming', 'complete', 'error', 'interrupted')
                    ),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                    ON messages(conversation_id, id);
                CREATE INDEX IF NOT EXISTS idx_conversations_updated
                    ON conversations(updated_at DESC);
                """
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _message_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "role": row["role"],
            "content": row["content"],
            "scope": row["scope"],
            "sources": json.loads(row["sources_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _conversation_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "message_count": row["message_count"] if "message_count" in row.keys() else 0,
        }

    def create_conversation(self) -> dict[str, Any]:
        conversation_id = str(uuid.uuid4())
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, DEFAULT_TITLE, now, now),
            )
        return self.get_conversation(conversation_id)  # type: ignore[return-value]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT c.*, COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                WHERE c.id = ?
                GROUP BY c.id
                """,
                (conversation_id,),
            ).fetchone()
        return self._conversation_dict(row) if row else None

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT c.*, COUNT(m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                GROUP BY c.id
                ORDER BY c.updated_at DESC, c.created_at DESC
                """
            ).fetchall()
        return [self._conversation_dict(row) for row in rows]

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
        return cursor.rowcount > 0

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [self._message_dict(row) for row in rows]

    def start_exchange(
        self, conversation_id: str, content: str, scope: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        now = _utc_now()
        with self._connect() as connection:
            conversation = connection.execute(
                "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if conversation is None:
                raise KeyError(conversation_id)

            user_count = connection.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND role = 'user'",
                (conversation_id,),
            ).fetchone()[0]
            if user_count == 0:
                connection.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (make_title(content), now, conversation_id),
                )
            else:
                connection.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conversation_id),
                )

            user_cursor = connection.execute(
                """
                INSERT INTO messages(
                    conversation_id, role, content, scope, sources_json, status, created_at
                ) VALUES (?, 'user', ?, ?, '[]', 'complete', ?)
                """,
                (conversation_id, content, scope, now),
            )
            assistant_cursor = connection.execute(
                """
                INSERT INTO messages(
                    conversation_id, role, content, scope, sources_json, status, created_at
                ) VALUES (?, 'assistant', '', NULL, '[]', 'streaming', ?)
                """,
                (conversation_id, now),
            )

        user = self.get_message(user_cursor.lastrowid)
        assistant = self.get_message(assistant_cursor.lastrowid)
        conversation_result = self.get_conversation(conversation_id)
        assert user and assistant and conversation_result
        return user, assistant, conversation_result

    def get_message(self, message_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        return self._message_dict(row) if row else None

    def finish_assistant(
        self,
        message_id: int,
        content: str,
        sources: list[dict[str, Any]],
        status: str = "complete",
    ) -> dict[str, Any]:
        if status not in {"complete", "error", "interrupted"}:
            raise ValueError(f"invalid assistant status: {status}")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT conversation_id FROM messages WHERE id = ? AND role = 'assistant'",
                (message_id,),
            ).fetchone()
            if row is None:
                raise KeyError(message_id)
            connection.execute(
                "UPDATE messages SET content = ?, sources_json = ?, status = ? WHERE id = ?",
                (content, json.dumps(sources, ensure_ascii=False), status, message_id),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (_utc_now(), row["conversation_id"]),
            )
        result = self.get_message(message_id)
        assert result
        return result

    def recover_streaming(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE messages SET status = 'interrupted' WHERE status = 'streaming'"
            )
        return cursor.rowcount

from __future__ import annotations

from pathlib import Path

import history


def test_history_persists_title_sources_and_cascade_delete(tmp_path: Path):
    database = tmp_path / "history.sqlite3"
    store = history.HistoryStore(database)
    conversation = store.create_conversation()

    user, assistant, updated = store.start_exchange(
        conversation["id"], "  첫 번째\n질문입니다  ", "전체"
    )
    saved = store.finish_assistant(
        assistant["id"],
        "저장된 답변",
        [{"label": "S1", "source_id": "notes", "relative_path": "a.md"}],
    )

    assert user["scope"] == "전체"
    assert updated["title"] == "첫 번째 질문입니다"
    assert saved["sources"][0]["relative_path"] == "a.md"

    reopened = history.HistoryStore(database)
    messages = reopened.list_messages(conversation["id"])
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "저장된 답변"

    assert reopened.delete_conversation(conversation["id"])
    assert reopened.list_messages(conversation["id"]) == []


def test_title_is_limited_to_40_characters():
    title = history.make_title("가" * 50)
    assert len(title) == 40
    assert title.endswith("…")


def test_conversations_are_sorted_by_latest_activity(tmp_path: Path, monkeypatch):
    timestamps = iter(
        [
            "2026-01-01T00:00:00.000+00:00",
            "2026-01-01T00:00:01.000+00:00",
            "2026-01-01T00:00:02.000+00:00",
        ]
    )
    monkeypatch.setattr(history, "_utc_now", lambda: next(timestamps))
    store = history.HistoryStore(tmp_path / "history.sqlite3")
    first = store.create_conversation()
    second = store.create_conversation()

    assert store.list_conversations()[0]["id"] == second["id"]
    store.start_exchange(first["id"], "새 활동", "전체")
    assert store.list_conversations()[0]["id"] == first["id"]


def test_recover_streaming_messages(tmp_path: Path):
    store = history.HistoryStore(tmp_path / "history.sqlite3")
    conversation = store.create_conversation()
    _, assistant, _ = store.start_exchange(conversation["id"], "질문", "전체")

    assert assistant["status"] == "streaming"
    assert store.recover_streaming() == 1
    recovered = store.get_message(assistant["id"])
    assert recovered and recovered["status"] == "interrupted"


def test_context_limits_and_retrieval_query():
    messages = []
    for index in range(8):
        messages.extend(
            [
                {"role": "user", "content": f"질문 {index}", "status": "complete"},
                {"role": "assistant", "content": f"답변 {index}", "status": "complete"},
            ]
        )
    messages.append({"role": "assistant", "content": "실패", "status": "error"})

    selected = history.select_chat_history(messages, max_turns=6, max_chars=12000)
    assert len(selected) == 12
    assert selected[0]["content"] == "질문 2"
    assert selected[-1]["content"] == "답변 7"

    short = history.select_chat_history(messages, max_turns=6, max_chars=10)
    assert sum(len(message["content"]) for message in short) <= 10

    query = history.build_retrieval_query("현재 질문", messages, history_turns=2)
    assert query == "질문 6\n질문 7\n현재 질문"


def test_retrieval_query_keeps_current_message_when_truncated():
    messages = [{"role": "user", "content": "이전" * 20, "status": "complete"}]
    query = history.build_retrieval_query("현재", messages, max_chars=10)
    assert len(query) == 10
    assert query.endswith("현재")

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import api
import history
import rag


class FakeIndex:
    def __init__(self, results):
        self.results = results
        self.queries: list[str] = []

    def query(self, question, _top_k, _min_similarity, where=None):
        self.queries.append(question)
        return self.results

    def stats(self):
        return {"document_count": 1, "chunk_count": 1, "last_indexed_at": None}

    def reindex(self, _sources):
        return SimpleNamespace(
            source_counts={}, updated_files=0, deleted_files=0,
            failed_files=[], total_chunks=1, rebuilt=False,
        )


class FakeChatClient:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return iter(
            [
                {"message": {"content": "테스트 "}},
                {"message": {"content": "답변"}},
            ]
        )


def make_runtime(tmp_path: Path, results=None, chat_error=None):
    retrieved = results if results is not None else [
        rag.RetrievedChunk(
            text="근거 문서",
            source_id="notes",
            source_type="markdown",
            relative_path="note.md",
            similarity=0.9,
            heading="제목",
        )
    ]
    index = FakeIndex(retrieved)
    chat = FakeChatClient(chat_error)
    runtime = api.Runtime(
        config={
            "ollama": {
                "host": "http://127.0.0.1:11434",
                "chat_model": "fake-chat",
                "embed_model": "fake-embed",
            },
            "default_note_folder": "Inbox",
            "top_k": 5,
            "min_similarity": 0.3,
            "chat_history_turns": 6,
            "chat_history_max_chars": 12000,
            "retrieval_history_turns": 2,
            "retrieval_query_max_chars": 4000,
        },
        sources=[],
        note_target_id="notes",
        vault_path=tmp_path,
        index=index,
        chat_client=chat,
        history_store=history.HistoryStore(tmp_path / "history.sqlite3"),
        ping_ollama=lambda: True,
        reindex_on_start=False,
    )
    return runtime, index, chat


def parse_events(response) -> list[dict]:
    return [
        json.loads(line[6:])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_conversation_crud_and_streaming_context(tmp_path: Path):
    runtime, index, chat = make_runtime(tmp_path)
    with TestClient(api.create_app(runtime, mount_frontend=False)) as client:
        created = client.post("/api/conversations")
        assert created.status_code == 201
        conversation = created.json()

        first = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"message": "첫 질문", "scope": "전체"},
        )
        first_events = parse_events(first)
        assert [event["type"] for event in first_events] == [
            "status", "status", "delta", "delta", "complete",
        ]
        assert first_events[-1]["message"]["content"] == "테스트 답변"
        assert first_events[-1]["message"]["sources"][0]["relative_path"] == "note.md"

        second = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"message": "후속 질문", "scope": "전체"},
        )
        assert second.status_code == 200
        assert index.queries[-1] == "첫 질문\n후속 질문"
        assert chat.calls[-1]["messages"][0] == {"role": "user", "content": "첫 질문"}
        assert chat.calls[-1]["messages"][1] == {"role": "assistant", "content": "테스트 답변"}

        listed = client.get("/api/conversations").json()
        assert listed[0]["title"] == "첫 질문"
        assert listed[0]["message_count"] == 4
        loaded = client.get(f"/api/conversations/{conversation['id']}/messages").json()
        assert len(loaded) == 4

        deleted = client.delete(f"/api/conversations/{conversation['id']}")
        assert deleted.status_code == 204
        assert client.get(f"/api/conversations/{conversation['id']}/messages").status_code == 404


def test_no_evidence_is_saved_without_model_call(tmp_path: Path):
    runtime, _, chat = make_runtime(tmp_path, results=[])
    with TestClient(api.create_app(runtime, mount_frontend=False)) as client:
        conversation = client.post("/api/conversations").json()
        response = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"message": "질문", "scope": "전체"},
        )
        events = parse_events(response)
        assert [event["type"] for event in events] == ["status", "complete"]
        assert events[-1]["message"]["content"] == rag.NO_EVIDENCE_ANSWER
        assert chat.calls == []


def test_model_error_is_persisted(tmp_path: Path):
    runtime, _, _ = make_runtime(tmp_path, chat_error=RuntimeError("모델 실패"))
    with TestClient(api.create_app(runtime, mount_frontend=False)) as client:
        conversation = client.post("/api/conversations").json()
        response = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"message": "질문", "scope": "전체"},
        )
        event = parse_events(response)[-1]
        assert event["type"] == "error"
        assert event["message"]["status"] == "error"
        assert "모델 실패" in event["message"]["content"]
        assert event["conversation"]["title"] == "질문"


def test_missing_conversation_and_invalid_scope(tmp_path: Path):
    runtime, _, _ = make_runtime(tmp_path)
    with TestClient(api.create_app(runtime, mount_frontend=False)) as client:
        assert client.get("/api/conversations/missing/messages").status_code == 404
        conversation = client.post("/api/conversations").json()
        response = client.post(
            f"/api/conversations/{conversation['id']}/messages",
            json={"message": "질문", "scope": "잘못된 범위"},
        )
        assert response.status_code == 422

"""FastAPI backend for the local React RAG application."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

import ollama
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import history
import rag
import vault

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class Runtime:
    config: dict[str, Any]
    sources: list[dict[str, Any]]
    note_target_id: str
    vault_path: Path
    index: Any
    chat_client: Any
    history_store: history.HistoryStore
    ping_ollama: Callable[[], bool]
    reindex_on_start: bool = True
    source_counts: dict[str, int] = field(default_factory=dict)


def _load_config(config_path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"{config_path} 없음. config.example.yaml을 복사하세요.")
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def _local_path(raw_path: str, base: Path) -> Path:
    path = Path(raw_path).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def build_runtime(config_path: Path = CONFIG_PATH) -> Runtime:
    config = _load_config(config_path)
    sources: list[dict[str, Any]] = config["sources"]
    note_target_id: str = config["note_target"]
    note_source = next((source for source in sources if source["id"] == note_target_id), None)
    if note_source is None:
        raise ValueError(f"note_target '{note_target_id}' not in sources")
    vault_path = rag.resolve_source_path(note_source)
    if vault_path is None:
        raise ValueError("note_target source path not found")

    ollama_config = config["ollama"]
    rag.assert_local_only(ollama_config["host"], ollama_config["chat_model"])
    rag.assert_local_only(ollama_config["host"], ollama_config["embed_model"])

    base = config_path.parent
    index = rag.RagIndex(
        index_path=_local_path(config["index_path"], base),
        ollama_host=ollama_config["host"],
        embed_model=ollama_config["embed_model"],
        chunk_version=config["chunk_version"],
        chunk_size_chars=config["chunk_size_chars"],
        chunk_overlap_chars=config["chunk_overlap_chars"],
        lines_per_chunk=config["lines_per_chunk"],
        overlap_lines=config["overlap_lines"],
    )
    chat_client = ollama.Client(host=ollama_config["host"])
    history_store = history.HistoryStore(
        _local_path(config.get("history_path", "./history.sqlite3"), base)
    )
    return Runtime(
        config=config,
        sources=sources,
        note_target_id=note_target_id,
        vault_path=vault_path,
        index=index,
        chat_client=chat_client,
        history_store=history_store,
        ping_ollama=lambda: rag.ping_ollama(ollama_config["host"]),
    )


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _source_refs(retrieved: list[rag.RetrievedChunk]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, chunk in enumerate(retrieved, start=1):
        refs.append(
            {
                "label": f"S{index}",
                "source_id": chunk.source_id,
                "relative_path": chunk.relative_path,
                "similarity": chunk.similarity,
                "heading": chunk.heading,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "provider": chunk.provider,
            }
        )
    return refs


class MessageRequest(BaseModel):
    message: str
    scope: str = "전체"


class SaveNoteRequest(BaseModel):
    title: str
    folder: str
    tags: str
    body: str


def create_app(runtime: Runtime, mount_frontend: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        recovered = runtime.history_store.recover_streaming()
        if recovered:
            logger.warning("중단된 대화 응답 %d개를 복구했습니다.", recovered)
        if runtime.reindex_on_start:
            logger.info("시작 시 전체 인덱싱...")
            summary = runtime.index.reindex(runtime.sources)
            runtime.source_counts.update(summary.source_counts)
            logger.info(
                "인덱싱 완료: 업데이트 %d, 삭제 %d, 실패 %d, 청크 %d",
                summary.updated_files,
                summary.deleted_files,
                len(summary.failed_files),
                summary.total_chunks,
            )
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def status_dict() -> dict[str, Any]:
        ollama_config = runtime.config["ollama"]
        stats = runtime.index.stats()
        return {
            "ollama_ok": runtime.ping_ollama(),
            "chat_model": ollama_config["chat_model"],
            "embed_model": ollama_config["embed_model"],
            "document_count": stats["document_count"],
            "chunk_count": stats["chunk_count"],
            "last_indexed_at": stats["last_indexed_at"],
            "source_counts": dict(runtime.source_counts),
        }

    @app.get("/api/status")
    def get_status():
        return status_dict()

    @app.get("/api/config")
    def get_config():
        return {
            "scope_options": rag.SCOPE_OPTIONS,
            "default_note_folder": runtime.config["default_note_folder"],
            "chat_model": runtime.config["ollama"]["chat_model"],
        }

    @app.post("/api/reindex")
    def post_reindex():
        summary = runtime.index.reindex(runtime.sources)
        runtime.source_counts.update(summary.source_counts)
        return {
            "updated_files": summary.updated_files,
            "deleted_files": summary.deleted_files,
            "failed_count": len(summary.failed_files),
            "total_chunks": summary.total_chunks,
            "rebuilt": summary.rebuilt,
            "status": status_dict(),
        }

    @app.get("/api/conversations")
    def get_conversations():
        return runtime.history_store.list_conversations()

    @app.post("/api/conversations", status_code=status.HTTP_201_CREATED)
    def post_conversation():
        return runtime.history_store.create_conversation()

    @app.get("/api/conversations/{conversation_id}/messages")
    def get_messages(conversation_id: str):
        if runtime.history_store.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
        return runtime.history_store.list_messages(conversation_id)

    @app.delete("/api/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_conversation(conversation_id: str):
        if not runtime.history_store.delete_conversation(conversation_id):
            raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    def stream_message(
        conversation_id: str,
        request: MessageRequest,
        previous_messages: list[dict[str, Any]],
        assistant_id: int,
    ) -> Iterator[str]:
        content_parts: list[str] = []
        finalized = False
        try:
            yield _sse({"type": "status", "stage": "retrieving"})
            query = history.build_retrieval_query(
                request.message,
                previous_messages,
                history_turns=runtime.config.get("retrieval_history_turns", 2),
                max_chars=runtime.config.get("retrieval_query_max_chars", 4000),
            )
            where = rag.scope_to_where(request.scope, runtime.note_target_id)
            retrieved = runtime.index.query(
                query,
                runtime.config["top_k"],
                runtime.config["min_similarity"],
                where=where,
            )

            if not retrieved:
                saved = runtime.history_store.finish_assistant(
                    assistant_id, rag.NO_EVIDENCE_ANSWER, [], "complete"
                )
                finalized = True
                yield _sse(
                    {
                        "type": "complete",
                        "message": saved,
                        "conversation": runtime.history_store.get_conversation(conversation_id),
                    }
                )
                return

            prompt = rag.build_answer_prompt(request.message, retrieved)
            chat_history = history.select_chat_history(
                previous_messages,
                max_turns=runtime.config.get("chat_history_turns", 6),
                max_chars=runtime.config.get("chat_history_max_chars", 12000),
            )
            model_messages = chat_history + [{"role": "user", "content": prompt}]
            yield _sse({"type": "status", "stage": "generating"})
            ollama_config = runtime.config["ollama"]
            response = runtime.chat_client.chat(
                model=ollama_config["chat_model"],
                messages=model_messages,
                stream=True,
                keep_alive=ollama_config.get("keep_alive", "30m"),
                # ponytail: qwen3 계열은 모델 기본 context length가 262144라 num_ctx를
                # 지정하지 않으면 매 요청마다 그만큼 KV 캐시를 잡아 크게 느려진다.
                options={"num_ctx": ollama_config.get("num_ctx", 8192)},
            )
            for chunk in response:
                content = chunk["message"]["content"]
                if content:
                    content_parts.append(content)
                    yield _sse({"type": "delta", "content": content})

            saved = runtime.history_store.finish_assistant(
                assistant_id, "".join(content_parts), _source_refs(retrieved), "complete"
            )
            finalized = True
            yield _sse(
                {
                    "type": "complete",
                    "message": saved,
                    "conversation": runtime.history_store.get_conversation(conversation_id),
                }
            )
        except GeneratorExit:
            raise
        except Exception as exc:  # noqa: BLE001 - local model/index errors become persisted chat errors
            error_text = f"오류: {exc}"
            saved = runtime.history_store.finish_assistant(
                assistant_id, "".join(content_parts) or error_text, [], "error"
            )
            finalized = True
            yield _sse(
                {
                    "type": "error",
                    "error": str(exc),
                    "message": saved,
                    "conversation": runtime.history_store.get_conversation(conversation_id),
                }
            )
        finally:
            if not finalized:
                runtime.history_store.finish_assistant(
                    assistant_id, "".join(content_parts), [], "interrupted"
                )

    @app.post("/api/conversations/{conversation_id}/messages")
    def post_message(conversation_id: str, request: MessageRequest):
        message = request.message.strip()
        if not message:
            raise HTTPException(status_code=422, detail="메시지를 입력하세요.")
        if request.scope not in rag.SCOPE_OPTIONS:
            raise HTTPException(status_code=422, detail="지원하지 않는 검색 범위입니다.")
        if runtime.history_store.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다.")

        previous_messages = runtime.history_store.list_messages(conversation_id)
        normalized_request = MessageRequest(message=message, scope=request.scope)
        _, assistant, _ = runtime.history_store.start_exchange(
            conversation_id, message, request.scope
        )
        return StreamingResponse(
            stream_message(
                conversation_id, normalized_request, previous_messages, assistant["id"]
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/save-note")
    def post_save_note(request: SaveNoteRequest):
        title = request.title.strip()
        body = request.body.strip()
        if not title or not body:
            return {"success": False, "message": "제목과 본문은 필수입니다."}

        tags = [tag.strip() for tag in request.tags.split(",") if tag.strip()]
        try:
            result = vault.write_note(
                runtime.vault_path,
                request.folder or runtime.config["default_note_folder"],
                title,
                tags,
                body,
            )
        except vault.VaultPathError as exc:
            return {"success": False, "message": f"파일 저장 실패: {exc}"}

        lines = [f"파일 저장 성공: {result.relative_path}"]
        commit = vault.commit_note(
            runtime.vault_path, result.path, f"Add note: {result.relative_path}"
        )
        lines.append("Git 커밋 성공" if commit.committed else f"Git 커밋 실패: {commit.error}")
        summary = runtime.index.reindex(runtime.sources)
        runtime.source_counts.update(summary.source_counts)
        lines.append(f"인덱싱: 신규/수정 {summary.updated_files}개, 청크 {summary.total_chunks}개")
        return {"success": True, "message": "\n".join(lines), "status": status_dict()}

    dist = PROJECT_ROOT / "frontend" / "dist"
    if mount_frontend and dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")
    return app


if __name__ == "__main__":
    uvicorn.run(create_app(build_runtime()), host="127.0.0.1", port=8000)

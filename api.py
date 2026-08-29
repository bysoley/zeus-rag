"""FastAPI backend — local RAG application."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import ollama
import uvicorn
import yaml
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import rag
import vault

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"{CONFIG_PATH} 없음. config.example.yaml을 복사하세요.")
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


config = _load_config()
sources: list[dict] = config["sources"]
note_target_id: str = config["note_target"]

_note_source = next((s for s in sources if s["id"] == note_target_id), None)
if _note_source is None:
    raise ValueError(f"note_target '{note_target_id}' not in sources")
vault_path = rag.resolve_source_path(_note_source)
if vault_path is None:
    raise ValueError(f"note_target source path not found")

ollama_cfg = config["ollama"]
rag.assert_local_only(ollama_cfg["host"], ollama_cfg["chat_model"])
rag.assert_local_only(ollama_cfg["host"], ollama_cfg["embed_model"])

index = rag.RagIndex(
    index_path=Path(config["index_path"]),
    ollama_host=ollama_cfg["host"],
    embed_model=ollama_cfg["embed_model"],
    chunk_version=config["chunk_version"],
    chunk_size_chars=config["chunk_size_chars"],
    chunk_overlap_chars=config["chunk_overlap_chars"],
    lines_per_chunk=config["lines_per_chunk"],
    overlap_lines=config["overlap_lines"],
)
chat_client = ollama.Client(host=ollama_cfg["host"])
_last_source_counts: dict[str, int] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("시작 시 전체 인덱싱...")
    summary = index.reindex(sources)
    _last_source_counts.update(summary.source_counts)
    logger.info(
        "인덱싱 완료: 업데이트 %d, 삭제 %d, 실패 %d, 청크 %d",
        summary.updated_files, summary.deleted_files,
        len(summary.failed_files), summary.total_chunks,
    )
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _status_dict() -> dict:
    ok = rag.ping_ollama(ollama_cfg["host"])
    stats = index.stats()
    return {
        "ollama_ok": ok,
        "chat_model": ollama_cfg["chat_model"],
        "embed_model": ollama_cfg["embed_model"],
        "document_count": stats["document_count"],
        "chunk_count": stats["chunk_count"],
        "last_indexed_at": stats["last_indexed_at"],
        "source_counts": dict(_last_source_counts),
    }


@app.get("/api/status")
def get_status():
    return _status_dict()


@app.get("/api/config")
def get_config():
    return {
        "scope_options": rag.SCOPE_OPTIONS,
        "default_note_folder": config["default_note_folder"],
        "chat_model": ollama_cfg["chat_model"],
    }


@app.post("/api/reindex")
def post_reindex():
    summary = index.reindex(sources)
    _last_source_counts.update(summary.source_counts)
    return {
        "updated_files": summary.updated_files,
        "deleted_files": summary.deleted_files,
        "failed_count": len(summary.failed_files),
        "total_chunks": summary.total_chunks,
        "rebuilt": summary.rebuilt,
        "status": _status_dict(),
    }


class AskRequest(BaseModel):
    message: str
    scope: str = "전체"


def _stream_ask(req: AskRequest):
    message = req.message.strip()
    if not message:
        yield f"data: {json.dumps({'done': True})}\n\n"
        return

    where = rag.scope_to_where(req.scope, note_target_id)
    retrieved = index.query(message, config["top_k"], config["min_similarity"], where=where)

    if not retrieved:
        yield f"data: {json.dumps({'content': rag.NO_EVIDENCE_ANSWER, 'done': True})}\n\n"
        return

    prompt = rag.build_answer_prompt(message, retrieved)
    try:
        response = chat_client.chat(
            model=ollama_cfg["chat_model"],
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        for chunk in response:
            content = chunk["message"]["content"]
            if content:
                yield f"data: {json.dumps({'content': content})}\n\n"
    except Exception as exc:
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        return

    source_lines = rag.format_sources(retrieved)
    yield f"data: {json.dumps({'sources': source_lines, 'done': True})}\n\n"


@app.post("/api/ask")
def post_ask(req: AskRequest):
    return StreamingResponse(_stream_ask(req), media_type="text/event-stream")


class SaveNoteRequest(BaseModel):
    title: str
    folder: str
    tags: str
    body: str


@app.post("/api/save-note")
def post_save_note(req: SaveNoteRequest):
    title = req.title.strip()
    body = req.body.strip()
    if not title or not body:
        return {"success": False, "message": "제목과 본문은 필수입니다."}

    tags = [t.strip() for t in req.tags.split(",") if t.strip()]
    try:
        result = vault.write_note(
            vault_path, req.folder or config["default_note_folder"], title, tags, body
        )
    except vault.VaultPathError as exc:
        return {"success": False, "message": f"파일 저장 실패: {exc}"}

    lines = [f"파일 저장 성공: {result.relative_path}"]
    commit = vault.commit_note(vault_path, result.path, f"Add note: {result.relative_path}")
    lines.append("Git 커밋 성공" if commit.committed else f"Git 커밋 실패: {commit.error}")

    reindex_summary = index.reindex(sources)
    _last_source_counts.update(reindex_summary.source_counts)
    lines.append(f"인덱싱: 신규/수정 {reindex_summary.updated_files}개, 청크 {reindex_summary.total_chunks}개")

    return {"success": True, "message": "\n".join(lines), "status": _status_dict()}


_dist = Path(__file__).parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)

"""로컬 RAG 애플리케이션 — Gradio 로컬 웹 UI (Ask / Save Note)."""
from __future__ import annotations

import logging
from pathlib import Path

import gradio as gr
import ollama
import yaml

import rag
import vault

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"{CONFIG_PATH} 가 없습니다. config.example.yaml을 config.yaml로 복사한 뒤 값을 채우세요."
        )
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


config = load_config()
sources: list[dict] = config["sources"]
note_target_id: str = config["note_target"]

_note_source = next((s for s in sources if s["id"] == note_target_id), None)
if _note_source is None:
    raise ValueError(f"note_target '{note_target_id}'에 해당하는 소스가 sources에 없습니다.")
vault_path = rag.resolve_source_path(_note_source)
if vault_path is None:
    raise ValueError(f"note_target 소스 '{note_target_id}'의 경로를 찾을 수 없습니다 (config.yaml의 path 확인).")

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

# 마지막 reindex의 소스별 파일 수 (claude-memory/codex-memory 상태 표시용)
_last_source_counts: dict[str, int] = {}


def _memory_status_line(source_id: str) -> str:
    count = _last_source_counts.get(source_id)
    if count is None:
        return f"{source_id}: 아직 인덱싱 안 됨"
    if count == 0:
        return f"{source_id}: disabled or no files found"
    return f"{source_id}: {count} files indexed"


def status_text() -> str:
    ok = rag.ping_ollama(ollama_cfg["host"])
    stats = index.stats()
    last = stats["last_indexed_at"] or "없음"
    lines = [
        f"Ollama: {'연결됨' if ok else '연결 안 됨'} | "
        f"채팅모델: {ollama_cfg['chat_model']} | 임베딩모델: {ollama_cfg['embed_model']}",
        f"인덱싱된 문서: {stats['document_count']}개, 청크: {stats['chunk_count']}개 | "
        f"마지막 인덱싱: {last}",
        _memory_status_line("claude-memory"),
        _memory_status_line("codex-memory"),
    ]
    return "\n".join(lines)


def do_reindex():
    summary = index.reindex(sources)
    _last_source_counts.update(summary.source_counts)
    msg = (
        f"업데이트 {summary.updated_files}개, 삭제 {summary.deleted_files}개, "
        f"실패 {len(summary.failed_files)}개, 청크 {summary.total_chunks}개"
        + (" (전체 재구축)" if summary.rebuilt else "")
    )
    if summary.failed_files:
        msg += "\n실패 파일: " + ", ".join(rel for rel, _ in summary.failed_files)
    return gr.update(value=msg, visible=True), status_text()


def ask(message: str, history: list[dict], scope: str):
    history = history or []
    message = message.strip()
    if not message:
        return history, ""

    where = rag.scope_to_where(scope, note_target_id)
    retrieved = index.query(message, config["top_k"], config["min_similarity"], where=where)
    if not retrieved:
        answer_block = rag.NO_EVIDENCE_ANSWER
    else:
        prompt = rag.build_answer_prompt(message, retrieved)
        response = chat_client.chat(
            model=ollama_cfg["chat_model"],
            messages=[{"role": "user", "content": prompt}],
        )
        answer = response["message"]["content"]
        source_lines = rag.format_sources(retrieved)
        answer_block = f"{answer}\n\n---\n출처:\n{source_lines}"

    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": answer_block},
    ]
    return history, ""


def clear_chat():
    return [], ""


def save_note(title: str, folder: str, tags_raw: str, body: str):
    title = (title or "").strip()
    body = (body or "").strip()
    if not title or not body:
        return "제목과 본문은 필수입니다.", status_text()

    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    try:
        result = vault.write_note(
            vault_path, folder or config["default_note_folder"], title, tags, body
        )
    except vault.VaultPathError as exc:
        return f"파일 저장 실패: {exc}", status_text()

    lines = [f"파일 저장 성공: {result.relative_path}"]

    commit = vault.commit_note(vault_path, result.path, f"Add note: {result.relative_path}")
    if commit.committed:
        lines.append("Git 커밋 성공")
    else:
        lines.append(f"Git 커밋 실패: {commit.error}")

    reindex_summary = index.reindex(sources)
    _last_source_counts.update(reindex_summary.source_counts)
    lines.append(
        f"인덱싱: 신규/수정 {reindex_summary.updated_files}개, 청크 {reindex_summary.total_chunks}개"
    )
    return "\n".join(lines), status_text()


with gr.Blocks(title="로컬 RAG 애플리케이션", analytics_enabled=False) as demo:
    gr.Markdown("## 로컬 RAG 애플리케이션")
    with gr.Row():
        status_box = gr.Textbox(
            label="상태", value=status_text(), interactive=False, lines=5, scale=4
        )
        reindex_btn = gr.Button("Reindex", scale=1)
    reindex_result = gr.Textbox(label="Reindex 결과", interactive=False, visible=False)

    with gr.Tab("Ask"):
        scope_box = gr.Dropdown(
            choices=rag.SCOPE_OPTIONS, value="전체", label="검색 범위"
        )
        chatbot = gr.Chatbot(label="대화", type="messages")
        question_box = gr.Textbox(label="질문", placeholder="로컬 자료에 대해 물어보세요")
        with gr.Row():
            send_btn = gr.Button("전송")
            clear_btn = gr.Button("대화 초기화")

        send_btn.click(ask, [question_box, chatbot, scope_box], [chatbot, question_box])
        question_box.submit(ask, [question_box, chatbot, scope_box], [chatbot, question_box])
        clear_btn.click(clear_chat, None, [chatbot, question_box])

    with gr.Tab("Save Note"):
        title_box = gr.Textbox(label="제목")
        folder_box = gr.Textbox(label="저장 폴더", value=config["default_note_folder"])
        tags_box = gr.Textbox(label="태그 (쉼표로 구분)")
        body_box = gr.Textbox(label="본문", lines=10)
        save_btn = gr.Button("저장")
        save_result = gr.Textbox(label="결과", interactive=False, lines=4)

        save_btn.click(
            save_note,
            [title_box, folder_box, tags_box, body_box],
            [save_result, status_box],
        )

    reindex_btn.click(do_reindex, None, [reindex_result, status_box])


if __name__ == "__main__":
    logger.info("시작 시 전체 인덱싱을 실행합니다...")
    startup_summary = index.reindex(sources)
    _last_source_counts.update(startup_summary.source_counts)
    logger.info(
        "인덱싱 완료: 업데이트 %d, 삭제 %d, 실패 %d, 청크 %d",
        startup_summary.updated_files,
        startup_summary.deleted_files,
        len(startup_summary.failed_files),
        startup_summary.total_chunks,
    )
    demo.launch(
        server_name="127.0.0.1",
        share=False,
        inbrowser=True,
        show_api=False,
    )

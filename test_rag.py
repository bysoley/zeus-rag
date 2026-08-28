"""rag.py/vault.py 핵심 로직 self-check. 실제 Ollama/Chroma 서버 연동 없이 결정적으로 동작한다.
fake_embed로 임베딩만 대체하고, 나머지(청킹/증분 재인덱싱/필터/경로 안전성)는 실제 로직을 그대로 검증한다.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import rag
import vault


def fake_embed(texts: list[str]) -> list[list[float]]:
    return [[b / 255.0 for b in hashlib.sha256(t.encode("utf-8")).digest()[:16]] for t in texts]


def _make_index(tmp_dir: Path) -> rag.RagIndex:
    return rag.RagIndex(
        index_path=tmp_dir / "index",
        ollama_host="http://127.0.0.1:11434",
        embed_model="fake-embed",
        chunk_version=1,
        embed_fn=fake_embed,
    )


def test_markdown_breadcrumb_chunking():
    text = "# Title\n\ncontent under title\n\n## Sub\n\ncontent under sub\n"
    chunks = rag.chunk_markdown(text, chunk_size=1000, overlap=50)
    assert any(c.breadcrumb == "Title" for c in chunks)
    assert any(c.breadcrumb == "Title > Sub" for c in chunks)
    print("OK: markdown breadcrumb chunking")


def test_code_line_numbers():
    text = "\n".join(f"line{i}" for i in range(1, 201))
    chunks = rag.chunk_code(text, lines_per_chunk=80, overlap_lines=10)
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 80
    assert chunks[1].start_line == 71  # 80 - 10(overlap) + 1
    print("OK: code chunk start_line/end_line")


def test_stale_chunks_removed_on_shrink():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        vault_dir = tmp_dir / "vault"
        vault_dir.mkdir()
        note = vault_dir / "note.md"
        note.write_text(
            "# H\n\n" + "\n\n".join(f"paragraph number {i} " * 40 for i in range(10)),
            encoding="utf-8",
        )

        index = _make_index(tmp_dir)
        sources = [{"id": "notes", "type": "markdown", "path": str(vault_dir)}]
        index.reindex(sources)
        chunk_count_before = index.stats()["chunk_count"]
        assert chunk_count_before > 1

        note.write_text("# H\n\nshort", encoding="utf-8")
        index.reindex(sources)
        chunk_count_after = index.stats()["chunk_count"]
        assert chunk_count_after < chunk_count_before

        remaining = index._collection.get(where={"source_id": "notes"})
        assert len(remaining["ids"]) == chunk_count_after
        print("OK: stale chunks removed after file shrinks")


def test_deleted_file_removed_from_index():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        vault_dir = tmp_dir / "vault"
        vault_dir.mkdir()
        note = vault_dir / "note.md"
        note.write_text("# H\n\nsome content", encoding="utf-8")

        index = _make_index(tmp_dir)
        sources = [{"id": "notes", "type": "markdown", "path": str(vault_dir)}]
        index.reindex(sources)
        assert index.stats()["document_count"] == 1

        note.unlink()
        summary = index.reindex(sources)
        assert summary.deleted_files == 1
        assert index.stats()["document_count"] == 0
        print("OK: deleted file removed from index")


def test_source_filter():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_dir = Path(tmp)
        vault_dir = tmp_dir / "vault"
        code_dir = tmp_dir / "code"
        vault_dir.mkdir()
        code_dir.mkdir()
        (vault_dir / "a.md").write_text("# A\n\nnote about apples", encoding="utf-8")
        (code_dir / "b.py").write_text("def f():\n    return 1\n", encoding="utf-8")

        index = _make_index(tmp_dir)
        sources = [
            {"id": "notes", "type": "markdown", "path": str(vault_dir)},
            {"id": "code", "type": "files", "path": str(code_dir)},
        ]
        index.reindex(sources)

        only_code = index.query("apples", top_k=10, min_similarity=-1, where={"source_id": "code"})
        assert len(only_code) == 1
        assert all(r.source_id == "code" for r in only_code)
        print("OK: source filter scopes query results")


def test_excluded_files_not_indexed():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        docs_dir = Path(tmp) / "docs"
        (docs_dir / "node_modules").mkdir(parents=True)
        (docs_dir / "node_modules" / "lib.js").write_text("ignored", encoding="utf-8")
        (docs_dir / ".env").write_text("SECRET=1", encoding="utf-8")
        (docs_dir / "keep.md").write_text("# Keep\n\nvisible content", encoding="utf-8")

        discovered = rag.discover_files_source(docs_dir)
        names = {p.name for p in discovered}
        assert "lib.js" not in names
        assert ".env" not in names
        assert "keep.md" in names
        print("OK: excluded dirs/files not indexed")


def test_path_env_overrides_path():
    env_key = "LOCAL_CONTEXT_ASSISTANT_TEST_PATH"
    try:
        os.environ[env_key] = "/from/env"
        resolved = rag.resolve_source_path(
            {"path_env": env_key, "path": "/from/config"}
        )
        assert resolved == Path("/from/env").expanduser().resolve()

        del os.environ[env_key]
        resolved = rag.resolve_source_path(
            {"path_env": env_key, "path": "/from/config"}
        )
        assert resolved == Path("/from/config").expanduser().resolve()
        print("OK: path_env overrides path when set, falls back otherwise")
    finally:
        os.environ.pop(env_key, None)


def test_note_path_traversal_blocked():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        vault_dir = Path(tmp) / "vault"
        vault_dir.mkdir()
        try:
            vault.write_note(vault_dir, "../../outside", "t", [], "body")
            raised = False
        except vault.VaultPathError:
            raised = True
        assert raised
        print("OK: note path traversal blocked")


def main():
    test_markdown_breadcrumb_chunking()
    test_code_line_numbers()
    test_stale_chunks_removed_on_shrink()
    test_deleted_file_removed_from_index()
    test_source_filter()
    test_excluded_files_not_indexed()
    test_path_env_overrides_path()
    test_note_path_traversal_blocked()
    print("모든 테스트 통과")


if __name__ == "__main__":
    main()

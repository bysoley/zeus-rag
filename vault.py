"""볼트에 노트를 안전하게 저장하고, 저장한 파일만 git으로 격리 커밋한다."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_WINDOWS_FORBIDDEN_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class VaultPathError(ValueError):
    """사용자 입력 경로가 볼트 밖을 가리키는 등 안전하지 않을 때."""


@dataclass
class SaveResult:
    path: Path
    relative_path: Path
    chars_written: int


@dataclass
class CommitResult:
    committed: bool
    error: str | None = None


def sanitize_component(raw: str, fallback: str = "note") -> str:
    """파일/폴더명 한 조각을 Windows에서 안전한 문자열로 정리한다."""
    text = unicodedata.normalize("NFC", raw or "").strip()
    text = _WINDOWS_FORBIDDEN_CHARS.sub("", text)
    text = text.strip(" .")  # 끝의 공백/점은 Windows에서 문제가 됨
    text = re.sub(r"\s+", "-", text)
    if not text:
        return fallback
    if text.upper() in _WINDOWS_RESERVED_NAMES:
        return f"{text}_"
    return text


def resolve_within_vault(vault_path: Path, *parts: str) -> Path:
    """vault_path 하위 경로로 resolve하고, 벗어나면 거부한다 (../ 등 경로 이탈 방지)."""
    vault_resolved = vault_path.resolve()
    candidate = vault_resolved.joinpath(*parts).resolve()
    if vault_resolved != candidate and vault_resolved not in candidate.parents:
        raise VaultPathError(f"'{candidate}'가 볼트 경로('{vault_resolved}') 밖입니다.")
    return candidate


def _build_frontmatter(title: str, tags: list[str], now: datetime) -> str:
    data = {
        "title": title,
        "date": now.astimezone().isoformat(timespec="seconds"),
        "tags": tags,
    }
    dumped = yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{dumped}\n---\n\n"


def write_note(
    vault_path: Path,
    folder: str,
    title: str,
    tags: list[str],
    body: str,
    now: datetime | None = None,
) -> SaveResult:
    """노트를 프런트매터 + 원문 그대로 볼트에 원자적으로 저장한다."""
    now = now or datetime.now(timezone.utc)
    raw_parts = Path(folder or "").parts
    if any(part in ("..", ".") or part.startswith(("/", "\\")) for part in raw_parts):
        raise VaultPathError(f"폴더 이름에 상대 이동 문자를 사용할 수 없습니다: '{folder}'")
    folder_parts = [sanitize_component(p) for p in raw_parts]
    target_dir = resolve_within_vault(vault_path, *folder_parts)
    target_dir.mkdir(parents=True, exist_ok=True)

    slug = sanitize_component(title, fallback="note")
    filename = f"{now:%Y%m%d-%H%M%S}-{slug}.md"
    final_path = resolve_within_vault(vault_path, *folder_parts, filename)

    content = _build_frontmatter(title, tags, now) + body

    tmp_path = final_path.with_suffix(final_path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp_path, final_path)  # 원자적 교체

    return SaveResult(
        path=final_path,
        relative_path=final_path.relative_to(vault_path.resolve()),
        chars_written=len(content),
    )


def _run_git(args: list[str], repo_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        shell=False,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def ensure_git_repo(repo_root: Path) -> None:
    if (repo_root / ".git").exists():
        _warn_if_hooks_present(repo_root)
        return
    _run_git(["init"], repo_root)
    logger.info("git repo가 없어 %s에 새로 init 했습니다.", repo_root)


def _warn_if_hooks_present(repo_root: Path) -> None:
    hooks_dir = repo_root / ".git" / "hooks"
    if not hooks_dir.exists():
        return
    active_hooks = [
        p.name for p in hooks_dir.iterdir()
        if p.is_file() and not p.name.endswith(".sample")
    ]
    if active_hooks:
        logger.warning(
            "볼트 git repo에 활성 hook이 있습니다 (%s). "
            "자동 커밋은 -c core.hooksPath= 로 이를 건너뜁니다.",
            ", ".join(active_hooks),
        )


def commit_note(repo_root: Path, note_abs_path: Path, message: str) -> CommitResult:
    """생성한 노트 파일 하나만 격리해서 커밋한다. push/fetch는 절대 하지 않는다."""
    try:
        ensure_git_repo(repo_root)
        rel = str(note_abs_path.resolve().relative_to(repo_root.resolve()))
        _run_git(["add", "--", rel], repo_root)
        _run_git(
            ["-c", "core.hooksPath=", "commit", "--only", "-m", message, "--", rel],
            repo_root,
        )
        return CommitResult(committed=True)
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        logger.error("git commit 실패: %s", err)
        return CommitResult(committed=False, error=err)
    except OSError as exc:
        # git이 PATH에 없는 경우 등
        logger.error("git 실행 실패: %s", exc)
        return CommitResult(committed=False, error=str(exc))


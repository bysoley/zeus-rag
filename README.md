# local-context-assistant

Fully local AI assistant that retrieves context from notes, AI memories, source code, and documents, and saves Git-versioned Markdown notes.

완전 로컬(Ollama)에서만 동작하는 개인용 컨텍스트 비서. Obsidian 볼트, Claude Code/Codex 메모리, 등록한 git 프로젝트, 일반 로컬 문서를 검색 대상으로 삼아 질문에 답하고, 채팅으로 남긴 메모는 Obsidian 볼트에 Markdown + git 커밋으로 저장한다. 회사 PC/개인 PC에 각각 독립적으로 설치하며, 두 PC 사이의 데이터 동기화는 하지 않는다.

## 1. 사전 준비

1. Python 3.10 이상 설치.
2. [Ollama](https://ollama.com) 설치.
3. 채팅/임베딩 모델 pull (예시, 실제 사용 전 한국어 노트로 비교 후 확정 권장):
   ```
   ollama pull qwen3:4b
   ollama pull embeddinggemma
   ```
4. 완전 로컬 모드로 Ollama 실행 (클라우드 기능 비활성화):
   ```
   # Windows PowerShell
   $env:OLLAMA_NO_CLOUD = "1"
   ollama serve
   ```

## 2. 설치

```
pip install -r requirements.txt
copy config.example.yaml config.yaml
```

`config.yaml`을 열어 각 소스의 `path`를 실제 경로로 채운다 (`~`는 홈 디렉터리로 확장됨). 이 파일은 PC마다 다르게 유지하며 git에 커밋하지 않는다 (`.gitignore`에 포함됨).

- `obsidian-notes`: Obsidian 볼트 경로 (유일한 쓰기 대상)
- `git_project` 소스들: 실제 git 저장소 경로를 하나씩 등록 (저장소가 아닌 폴더는 `files` 타입으로)
- `claude-memory`/`codex-memory`: 경로 자동 탐지라 `path` 불필요, 설치가 안 돼 있으면 자동으로 "0 files" 처리됨

## 3. 실행

```
python app.py
```

- 최초 실행 시 등록된 모든 소스를 전체 인덱싱한다 (문서/코드 양에 따라 시간이 걸릴 수 있음).
- 브라우저가 자동으로 열린다 (`http://127.0.0.1:<포트>`).
- **Ask 탭**: 검색 범위(전체/AI 메모리/Obsidian/프로젝트/로컬 문서)를 고르고 질문 → 답변과 출처가 함께 표시됨.
- **Save Note 탭**: 제목/폴더/태그/본문 입력 후 저장 → Obsidian 볼트에 파일 저장, 그 파일만 git 커밋, 즉시 재인덱싱.
- 상단 **Reindex** 버튼으로 언제든 수동 재인덱싱 가능 (파일 워처는 1차 범위에 없음).

## 4. 테스트

실제 Ollama 없이 결정적으로 동작하는 self-check:

```
python test_rag.py
```

## 5. 검증 체크리스트

- [ ] `config.yaml`의 각 소스 경로가 정확히 인식되는지 (상태 영역에 문서/청크 수 표시)
- [ ] 경로가 없는 소스는 앱이 죽지 않고 경고만 뜨는지
- [ ] Ask 탭에서 볼트/프로젝트 실제 내용을 질문 → 출처(`source_id:relative_path`, 헤더 또는 줄 번호)가 정확한지
- [ ] 근거 없는 질문에는 "로컬 자료에서 근거를 찾지 못했습니다" 응답이 오는지
- [ ] Save Note 저장 → `git log --follow -- <path>`로 해당 파일만 커밋됐는지 (기존에 stage된 다른 변경과 안 섞였는지)
- [ ] 노트 저장 직후 Ask 탭에서 바로 검색되는지 (증분 재인덱싱)
- [ ] 파일 수정/삭제 후 Reindex → 오래된 청크가 사라지는지
- [ ] `../` 등 경로 이탈 입력 시 저장이 거부되는지
- [ ] **네트워크 연결을 끊은 상태**에서 위 전체 흐름을 재실행해 외부 통신 없이 동작하는지 확인 (모델 pull/`pip install` 이후 최종 증빙 단계)
- [ ] 두 번째 PC(개인 PC)에 동일하게 설치 → 각자의 `config.yaml`로 독립 동작하는지 (동기화 없음)

## 범위 밖 (1차)

- PC 간 데이터 동기화, 클라우드 LLM/임베딩
- PDF/DOCX/HWP/이미지 OCR
- AI 어시스턴트 전용 DB(SQLite 등) 파서, AST/Tree-sitter 기반 코드 분석
- 파일 워처 기반 자동 재인덱싱, 일정/리마인더
- `.exe` 설치 파일, 시스템 트레이 상주, 자동 시작
- git push/pull/fetch 자동 실행, 대화 기록 영구 저장(1차는 세션 한정)

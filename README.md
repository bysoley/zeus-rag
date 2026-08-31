# local-context-assistant

Ollama를 이용해 노트, AI 메모리, 소스코드와 문서를 검색하고 Git으로 마크다운 메모를 관리하는 로컬 RAG 애플리케이션.

- 완전 로컬(Ollama)에서만 동작한다.
- Obsidian 볼트, Claude Code/Codex 메모리, 등록한 git 프로젝트, 일반 로컬 문서를 검색 대상으로 삼아 질문에 답하고, 채팅으로 남긴 메모는 Obsidian 볼트에 Markdown + git 커밋으로 저장한다.
- 대화 기록은 로컬 SQLite에 보관하며 PC 사이에 데이터 동기화는 하지 않는다.

## 주요 기능

- 여러 로컬 소스를 하나의 Chroma 인덱스로 구성하고 검색 범위를 필터링한다.
- Ollama 임베딩과 채팅 모델로 근거 기반 답변을 생성하고 파일·헤더·줄 번호 출처를 표시한다.
- 답변을 SSE로 스트리밍하고, 여러 대화와 메시지를 SQLite에 저장한다.
- Obsidian 볼트에 메모를 저장하고 해당 파일만 git 커밋한 뒤 즉시 재인덱싱한다.
- 시작 시 전체 소스를 증분 재인덱싱하고 UI에서 수동 Reindex를 실행할 수 있다.

## 구성

```text
React + TypeScript + Vite
          │ JSON / SSE
          ▼
       FastAPI
       ├─ Ollama        채팅·임베딩
       ├─ Chroma        로컬 벡터 인덱스
       ├─ SQLite        대화·메시지 기록
       └─ Obsidian/Git  Markdown 메모 저장
```

## 1. 사전 준비

1. Python 3.10 이상 설치.
2. Node.js 18 이상과 npm 설치.
3. Git CLI 설치.
4. [Ollama](https://ollama.com) 설치.
5. 채팅/임베딩 모델 pull (예시, 실제 사용 전 한국어 노트로 비교 후 확정 권장):
   ```
   ollama pull qwen3:4b
   ollama pull embeddinggemma
   ```
6. 완전 로컬 모드로 Ollama 실행 (클라우드 기능 비활성화):
   ```
   # Windows PowerShell
   $env:OLLAMA_NO_CLOUD = "1"
   ollama serve
   ```

## 2. 설치

```
python -m pip install -r requirements.txt
copy config.example.yaml config.yaml
npm --prefix frontend ci
```

`config.yaml`을 열어 각 소스의 `path`를 실제 경로로 채운다 (`~`는 홈 디렉터리로 확장됨). 이 파일은 PC마다 다르게 유지하며 git에 커밋하지 않는다 (`.gitignore`에 포함됨).

PC마다 등록할 소스 자체가 다르면(예: 회사 git 프로젝트는 회사 PC에만 존재) 어차피 `sources:` 목록을 다시 구성해야 하지만, 경로만 다르고 구조는 같은 소스(대표적으로 `obsidian-notes`)는 `path_env`로 PC 간 차이를 흡수할 수 있다:

```yaml
- id: obsidian-notes
  type: markdown
  path_env: OBSIDIAN_VAULT_PATH # 설정돼 있으면 이 값이 path보다 우선
  path: "~/Documents/ObsidianVault"
  writable: true
```

```
# Windows PowerShell, PC마다 다르게 설정
$env:OBSIDIAN_VAULT_PATH = "D:/Notes/MyVault"
```

이렇게 해두면 `config.yaml` 자체는 두 PC에서 동일하게 유지하고, 환경변수만 PC별로 다르게 설정하면 된다.

- `obsidian-notes`: Obsidian 볼트 경로 (유일한 쓰기 대상)
- `git_project` 소스들: 실제 git 저장소 경로를 하나씩 등록 (저장소가 아닌 폴더는 `files` 타입으로)
- `claude-memory`/`codex-memory`: 경로 자동 탐지라 `path` 불필요, 설치가 안 돼 있으면 자동으로 "0 files" 처리됨

## 3. 프로젝트 구조

```text
api.py                 FastAPI API, SSE 스트리밍, 프론트엔드 서빙
history.py             SQLite 대화·메시지 저장과 문맥 선택
rag.py                 소스 탐색, 청킹, Chroma 인덱싱·검색
vault.py               Obsidian 메모 저장과 단일 파일 git 커밋
frontend/              React + TypeScript UI
config.example.yaml    로컬 설정 예시
test_*.py              API, 대화 기록, RAG 검증
```

## 4. 개발 실행

터미널 1에서 FastAPI 백엔드를 실행한다.

```
python api.py
```

터미널 2에서 React 개발 서버를 실행한다.

```
npm --prefix frontend run dev
```

브라우저에서 `http://127.0.0.1:5173`을 연다. React 개발 서버는 `/api` 요청을 `http://127.0.0.1:8000`으로 전달한다.

프로덕션 빌드를 FastAPI에서 함께 제공하려면 다음과 같이 실행한다.

```
npm --prefix frontend run build
python api.py
```

- 브라우저에서 `http://127.0.0.1:8000`을 연다.
- 최초 실행 시 등록된 모든 소스를 전체 인덱싱한다 (문서/코드 양에 따라 시간이 걸릴 수 있음).
- **대화**: 전체, AI 메모리, Claude, Codex, Obsidian, 프로젝트, 로컬 문서 중 검색 범위를 고르고 질문한다. 답변은 스트리밍되며 출처와 유사도가 함께 표시된다.
- 여러 대화를 만들어 다시 열거나 삭제할 수 있고, 후속 질문에는 설정된 최근 대화 문맥이 반영된다.
- 대화와 메시지는 기본적으로 프로젝트 루트의 `history.sqlite3`에 저장된다. 삭제 확인 후 지운 대화는 즉시 영구 삭제된다.
- 앱이 비정상 종료되면 다음 실행 시 완료되지 않은 스트리밍 응답을 `interrupted` 상태로 복구한다.
- **노트 저장**: 제목/폴더/태그/본문을 입력하면 Obsidian 볼트에 파일 저장, 해당 파일만 git 커밋, 즉시 재인덱싱한다.
- 사이드바의 **Reindex** 버튼으로 언제든 수동 재인덱싱할 수 있다 (파일 워처는 1차 범위에 없음).

## 5. 테스트

개발 의존성을 설치한 뒤 실제 Ollama 없이 결정적인 단위 테스트를 실행한다.

```
python -m pip install -r requirements-dev.txt
python -m pytest
npm --prefix frontend run build
```

## 6. 검증 체크리스트

- [ ] `config.yaml`의 각 소스 경로가 정확히 인식되는지 (상태 영역에 문서/청크 수 표시)
- [ ] 경로가 없는 소스는 앱이 죽지 않고 경고만 뜨는지
- [ ] 대화 화면에서 볼트/프로젝트 실제 내용을 질문 → 출처(`source_id:relative_path`, 헤더 또는 줄 번호)가 정확한지
- [ ] 앱을 재시작해도 대화 목록과 메시지가 복원되는지
- [ ] 후속 질문이 같은 대화의 최근 문맥을 이해하는지
- [ ] 대화 삭제 확인 후 목록과 `history.sqlite3`에서 메시지까지 제거되는지
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
- AI 어시스턴트 전용 DB 파서, AST/Tree-sitter 기반 코드 분석
- 파일 워처 기반 자동 재인덱싱, 일정/리마인더
- `.exe` 설치 파일, 시스템 트레이 상주, 자동 시작
- git push/pull/fetch 자동 실행, 대화 기록 클라우드 동기화

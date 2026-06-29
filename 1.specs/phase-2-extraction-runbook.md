# Phase 2 Extraction Runbook — for Hermes + DeepSeek Pro

목표: 수집된 27개 에피소드 원문을 DeepSeek Pro로 엑기스(`data/extracts/epNN.json`)로 변환하고, 위키를 렌더한다.

작업 주체: MacBook Hermes 에이전트(DeepSeek Pro). 이 문서의 단계를 그대로 수행하면 된다.

## 사전 상태 (Claude가 준비해 둔 것)

- 원문 27편: `~/BaseCamp/06_Artifacts/aifrontier-wiki/raw/epNN/` (page.html, text.txt, meta.json).
- llms-full 코퍼스: `raw/_site/llms-full.txt`.
- **추출 잡 27개** (이미 조립된 프롬프트): `~/BaseCamp/06_Artifacts/aifrontier-wiki/extract-jobs/`
  - `epNN.messages.json` — `{ep_id, output_path, response_format:"json_object", messages:[system,user]}` (프로그램용)
  - `epNN.prompt.md` — 같은 내용의 사람/에이전트 가독본
- 시스템 프롬프트 원본: `0.prompt/extract-prompt.md`.
- 출력 스키마: `data/extract.schema.json`.

각 잡의 `messages`는 system(추출 지침) + user(메타데이터 + llms-full 요약 + 전사)로 이미 조립돼 있다. 입력 조립은 다시 할 필요 없다.

## 경로 A — 자동 (권장): 내장 deepseek 어댑터

1. 엔드포인트 설정: `config/local.env.example`를 `config/local.env`로 복사하고 채운다.
   - `AIFRONTIER_LLM_BASE_URL` (예: `http://localhost:8000/v1` — Hermes의 OpenAI 호환 게이트웨이)
   - `AIFRONTIER_LLM_MODEL` (예: `deepseek-pro`)
   - 비로컬 엔드포인트면 `AIFRONTIER_LLM_API_KEY`도. (로컬이면 키 불필요.)
   - 이 파일은 `.gitignore`로 커밋 금지.
2. 환경 로드 후 배치 실행(자동 재시도 없음, 배치 단위로):
   ```bash
   set -a; . config/local.env; set +a
   python3 scripts/aifrontier_wiki.py extract --allow-llm --adapter deepseek --limit 5
   ```
   - `--limit`로 한 번에 처리량을 제한한다(예: 5편씩). 이미 추출된 편은 자동으로 건너뛴다.
   - 특정 편만: `--episode 96`. 재추출: `--force`.
   - 어댑터는 응답 JSON을 `data/extract.schema.json` + 불변식(ep_id 일치, entity id 유일)으로 **검증한 뒤에만** `data/extracts/epNN.json`에 쓴다. 검증 실패 시 파일을 쓰지 않고 사유를 출력한다.
3. 27편이 모두 추출될 때까지 2를 반복한다.

## 경로 B — 수동/대체: 익스포트된 잡 실행

게이트웨이를 쓰지 않을 때. 각 `epNN.messages.json`의 `messages`를 DeepSeek Pro에 그대로 넣고(JSON 모드), 반환된 **단일 JSON 객체**를 `data/extracts/epNN.json`으로 저장한다. 저장 후 반드시 `validate`로 검증한다(아래).

## 추출 후 마무리 (공통)

```bash
python3 scripts/aifrontier_wiki.py validate          # 스키마/불변식/정합성
python3 scripts/aifrontier_wiki.py build-keyword-index
python3 scripts/aifrontier_wiki.py render-wiki        # canonical 2.wiki 생성
python3 scripts/aifrontier_wiki.py validate           # 렌더 후 재검증
python3 scripts/aifrontier_wiki.py selfcheck
```

`validate`가 통과하면 `2.wiki/index.html`을 열어 표본 2~3편을 사람이 검수한다. 문제 있으면 해당 편만 `--force`로 재추출한다.

## 품질 체크 (검수 포인트)

- `one_line`이 과장 없이 핵심을 담았는가.
- `entities`의 모든 키워드가 `body_paragraphs`에 실제로 등장하는가(앵커링 전제). 등장하지 않으면 그 키워드는 본문 클릭 이동이 안 된다 → 프롬프트가 이를 강제하지만 표본 확인.
- `flow`가 Chapters를 의미 단위로 잘 압축했는가.
- 잘못된 사실/환각이 없는가(전사에 근거).

## 규칙

- 네트워크/LLM은 명시적 플래그가 있을 때만. 시크릿은 `config/local.env`에서만, 커밋·노출 금지.
- 실패는 자동 재시도하지 않는다. 실패 편을 기록하고 다음 배치로 진행, 사람에게 보고.
- 한 회차가 끝나면 `state/change-history.jsonl`에 요약 한 줄을 남기고, 위키 변경을 1커밋으로 묶는다.
- 대량 원문/잡 파일은 `06_Artifacts`에 둔다(repo에 커밋하지 않는다).

## Definition of Done (Phase 2)

- `data/extracts/`에 27개(또는 추출 가능한 전 편) 스키마-유효 JSON.
- `validate` + `selfcheck` PASS, `2.wiki/`에 인덱스·에피소드·키워드 페이지 생성.
- 표본 검수 통과. 이후 주간 회차는 신규/변경 에피소드만 증분 처리.

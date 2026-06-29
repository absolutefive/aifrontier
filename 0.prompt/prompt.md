# Recurring Cycle Prompt — AI Frontier Wiki

대상 작업자: MacBook Hermes (DeepSeek Pro). Mac mini 스케줄러가 주 1회 SSH로 호출.

목표: aifrontier.kr 한국어 신규/변경 에피소드만 증분 처리해 위키를 최신으로 유지한다.

절차:

1. `cd ~/BaseCamp/02_Knowledge/research/aifrontier-wiki`
2. `python3 scripts/aifrontier_wiki.py validate` — 실패 시 중단하고 보고.
3. `python3 scripts/aifrontier_wiki.py fetch-index --allow-network` — episodes.json 갱신, 신규/변경 식별.
4. 신규/변경이 없으면 "no material change"로 종료(렌더/커밋 없음).
5. 있으면: `fetch-pages --allow-network --limit <n>` → 원문 아카이브.
6. `extract --allow-llm --adapter deepseek --limit <n>` — 신규/변경 에피소드만 추출.
7. `build-keyword-index` → `render-wiki`.
8. 변경 요약을 `state/change-history.jsonl`에 남기고, 위키 1커밋(있을 때만).

원칙:

- 네트워크/LLM은 명시적 플래그가 있을 때만.
- 정상 회차당 최대 1커밋. 변경 없으면 repo를 깨끗이 둔다.
- 실패는 자동 재시도하지 않고 run-status에 기록 후 사람에게 보고.
- 시크릿은 config/local.env(+env)에서만. 절대 커밋·노출 금지.
- 사람이 읽는 산출물(위키)은 가독성을 최우선으로 한다.

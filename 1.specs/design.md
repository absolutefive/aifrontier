# Design — AI Frontier Wiki Pipeline

상태: Phase 0 (scaffold). 작업자: MacBook Hermes / DeepSeek Pro / Maggie.

## 1. Goal

aifrontier.kr 한국어 에피소드를 수집 → 엑기스 추출 → 읽기용 위키로 렌더하고, 주 1회 증분 갱신한다.

## 2. Pipeline stages

```text
fetch-index  →  fetch-pages  →  extract  →  build-keyword-index  →  render-wiki
 (network)      (network)       (LLM)        (deterministic)        (deterministic)
```

- `fetch-index` (Phase 1): sitemap.xml + llms.txt 파싱 → `data/episodes.json` 갱신. 신규/변경만 표시.
- `fetch-pages` (Phase 1): ko 에피소드 원문 다운로드 → `06_Artifacts/aifrontier-wiki/raw/epNN/`. content_hash로 변경 감지.
- `extract` (Phase 2): DeepSeek Pro가 원문 → `data/extracts/epNN.json` (엑기스). 배치(기본 5)·재개 가능·자동 재시도 없음.
- `build-keyword-index` (Phase 3): 모든 extract를 모아 `data/keyword-index.json` 생성.
- `render-wiki` (Phase 3): extract + keyword-index → `2.wiki/` 정적 HTML.

기본 실행은 네트워크/LLM 없는 결정적 경로만 수행한다. 각 단계는 `state/run-status.json`·`change-history.jsonl`에 기록을 남기고 중단 후 재개 가능해야 한다.

## 3. Data model

- `data/episodes.json` — 정규 에피소드 인덱스 (id, url, status, content_hash, last_seen).
- `data/extracts/epNN.json` — 에피소드별 엑기스. 스키마: `data/extract.schema.json`.
- `data/keyword-index.json` — 키워드 → 등장 에피소드 집계. 스키마: `data/keyword-index.schema.json`.

### Extract 핵심 필드

- `one_line`, `key_points[]`, `flow[]`, `body_paragraphs[]`
- `entities[]` = `{id, label, type(concept|person|model), aliases[]}`
  - `aliases`는 본문 표면형 매칭에 사용한다 (예: `DeepSeek-V4` ↔ `딥시크 V4`). render가 별칭까지 검색해 occurrence를 wrap한다.
- `notable_quote`, `review_status(draft|reviewed|promoted)`

## 4. Keyword navigation (rendered)

요구사항(보스 확정):

1. 에피소드 페이지의 키워드 칩을 누르면 그 키워드가 등장한 에피소드 목록(등장 횟수 포함)이 펼쳐진다.
2. 현재 글 행을 누르면 본문의 해당 키워드 첫 등장 위치로 이동한다.
3. 키워드는 한 에피소드에서 여러 번 등장하므로 `‹ n / total ›` 이전·다음 스테퍼로 본문을 순회한다.
4. 다른 에피소드 행은 `episodes/epNN.html#키워드-1`로 연결된다.

구현 규칙:

- render는 본문 occurrence를 `<mark class="term" id="{kw}-{n}" data-kw="{kw}">…</mark>`로 wrap하고 안정적 앵커를 만든다.
- 각 페이지에 그 페이지 키워드의 에피소드 목록을 `<script type="application/json" id="afw-data">`로 **인라인**한다. (file:// 환경엔 fetch/CORS가 없으므로 외부 JSON 로드 금지.)
- 동작 스크립트는 로컬 `assets/wiki.js` 한 장으로 공유한다 (CDN 의존 없음).

## 5. Keyword index page

- `2.wiki/keywords/index.html` — 전체 키워드를 개념/인물/모델로 묶고 빈도순 정렬, 검색 필터 제공.
- 키워드 클릭 → 등장 에피소드 목록 → 각 행은 `../episodes/epNN.html#키워드-1`로 연결.
- 전체 키워드 인덱스 JSON을 `<script type="application/json" id="afk-data">`로 인라인.

## 6. Safety / discipline

- 네트워크·LLM은 명시적 플래그가 있어야만 동작. 기본은 로컬 전용.
- 시크릿은 `config/local.env`(+env), 절대 커밋 금지.
- 스케줄러 기본 비활성, 7일 주기, 14일 가드, launchd는 템플릿만.
- 정상 회차당 1 commit. 변경 없으면 "no material change"로 깨끗이 종료.

## 7. Open items (Phase 1+에서 확정)

- 에피소드 페이지의 정확한 본문 셀렉터/추출 방식 (llms.txt 우선 vs HTML 파싱).
- 별칭 매칭의 경계(부분어 오탐 방지: 토큰 경계/최장일치 우선).
- 다국어 확장 시 id 충돌 규칙 (현재 ko 단일).

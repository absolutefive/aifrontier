# HTML Information Architecture — AI Frontier Wiki

위키는 로컬 자산만 쓰는 정적 HTML이다. `assets/styles/wiki.css` 한 장과 `assets/wiki.js` 한 장을 공유하며 외부 CDN·폰트·네트워크에 의존하지 않는다. 라이트/다크 모드는 `prefers-color-scheme`로 대응한다.

## Pages

1. `2.wiki/index.html` — 위키 홈
2. `2.wiki/episodes/epNN.html` — 에피소드 엑기스 페이지
3. `2.wiki/keywords/index.html` — 키워드 인덱스 페이지

상대 경로 깊이:
- `index.html` → 자산은 `../assets/...`
- `episodes/epNN.html`, `keywords/index.html` → 자산은 `../../assets/...`

## index.html

- 헤더: 사이트명, 갱신일, 주기 안내
- 통계 카드: 에피소드 수, 추출 수, 이번 주 신규, 추출 모델
- 주제 태그 줄(개념/인물/모델 상위)
- 에피소드 카드 리스트(최신순): EP번호·날짜·제목·one_line·태그, `episodes/epNN.html`로 링크
- 푸터: 출처/생성 정보

## episodes/epNN.html

필수 섹션:

1. 머리말: 카테고리, `EP{N}`, 날짜·진행자, 제목(h1)
2. 한 줄 결론 (`one_line`, voice/serif 강조 blockquote)
3. 핵심 포인트 (`key_points`, 불릿)
4. 다룬 흐름 (`flow`, stage→summary 타임라인) — 있을 때만
5. 본문 엑기스 (`body_paragraphs`) — occurrence는 `<mark class="term" id="{kw}-{n}" data-kw="{kw}">`
6. 등장 개념·인물·모델 (`entities` → 칩 버튼 `.kwchip[data-kw]`)
   - 칩 패널 `#afw-panel`(처음 비표시) + 스테퍼 `‹ n/total ›`
7. 인용 (`notable_quote`) — 있을 때만
8. 출처·원문: source_url 링크 + `06_Artifacts` raw 경로(code)
9. 푸터: 추출 모델, 추출일, review_status 배지

임베드: `<script type="application/json" id="afw-data">{ epId, keywords:{ kw:{label,type,eps:[{ep,c,cur}]} } }</script>` 뒤에 `<script src="../../assets/wiki.js">`.

## keywords/index.html

- 헤더 + 통계(키워드 수, 에피소드 수, 최다 등장)
- 검색 입력 `#afk-q` (라벨 부분일치 필터)
- 그룹 컨테이너 `#afk-groups`: 개념/인물/모델, 각 군 빈도순
- 선택 패널 `#afk-panel`: 키워드명 + "n개 에피소드 · m회 등장" + 에피소드 행(→ `../episodes/epNN.html#kw-1`)
- 임베드: `<script type="application/json" id="afk-data">[ {id,label,type,total,eps:[{ep_id,count,first_anchor}]} ]</script>` 뒤에 `<script src="../../assets/wiki.js">`.

## Layout rules

- 밀도 있고 스캔하기 쉽게. 본문은 가독 우선(line-height 1.7~1.85).
- 색상은 의미 인코딩(개념=teal, 인물=coral, 모델=purple, 상태=semantic)만, 2~3 ramp 이내.
- 외부 폰트·JS 라이브러리·네트워크 자산 금지. `wiki.js`는 바닐라.
- 모든 링크는 보이고 복사 가능하게.
- 큰 원문/로그/스크린샷은 위키 트리에 넣지 않는다.

## wiki.js contract

- `#afw-body`가 있으면 에피소드 모드: 칩 클릭→occurrence 하이라이트+패널+스테퍼.
- `#afk-groups`가 있으면 인덱스 모드: 그룹 빌드+검색+선택 패널.
- 두 모드 모두 인라인 JSON(`#afw-data`/`#afk-data`)만 읽고 외부 요청을 하지 않는다.

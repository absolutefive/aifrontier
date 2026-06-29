# Validation Checklist — AI Frontier Wiki

## Phase 0 (scaffold) — must pass now

- [ ] `python3 scripts/aifrontier_wiki.py validate` → `VALIDATE: PASS`
- [ ] `python3 scripts/aifrontier_wiki.py selfcheck` → `SELFCHECK: PASS`
- [ ] Required files present: README, sources, specs, schemas, state, assets, prompts, scripts.
- [ ] `state/scheduler-state.json` has `enabled: false`, `cycle_days: 7`, `guard_days: 14`.
- [ ] `data/episodes.json` parses and is an empty `episodes: []` seed.
- [ ] Canonical `2.wiki/` holds no episode/index HTML until real extracts exist (only `.gitkeep`).
- [ ] `render-wiki --demo-fixture 1.specs/fixtures/ep96-extract.fixture.json` writes ONLY under `preview/` (gitignored), prints the SAMPLE notice, and leaves `2.wiki/`, `data/`, `state/` untouched.
- [ ] Preview episode page: clicking a keyword chip highlights body occurrences, shows the episode list, and the `‹ n/total ›` stepper cycles occurrences.
- [ ] Preview keyword page: search filters keywords; clicking a keyword lists episodes; rows link to `../episodes/epNN.html#kw-1`.
- [ ] No external network/CDN/font references in any generated HTML (assets are local relative paths only).

### Source-of-truth invariants (enforced by `validate`)

- [ ] Canonical `2.wiki` is a pure function of `data/extracts`: no `episodes/ep*.html` without a matching extract (no orphans).
- [ ] `data/keyword-index.json` equals a fresh recompute from `data/extracts` (not stale).
- [ ] `state/current-state.json` counts (extracted / rendered / keywords) match reality.
- [ ] Schemas enforced: extract/episodes/keyword-index validated by type, enum, and id pattern.
- [ ] Cross-record invariants: unique `ep_id`; filename `epN.json` matches `ep_id`; unique entity ids per episode; stable (label, type) for a keyword id across episodes.

## Network/LLM stages (must refuse in Phase 0)

- [ ] `fetch-index` / `fetch-pages` without `--allow-network` → refuse with exit 2.
- [ ] `extract` without `--allow-llm` → refuse with exit 2.
- [ ] With the opt-in flag, Phase 0 prints "not implemented" and exits 2 (no side effects).

## Phase 1 (collect) — implemented

- [x] `fetch-index --allow-network` populates `episodes.json` from sitemap (27 ko episodes) and snapshots `llms.txt`/`llms-full.txt`.
- [x] `fetch-pages` stores originals only under `06_Artifacts/aifrontier-wiki/raw/epNN/` (page.html, text.txt, next-data.json, meta.json); nothing bulky under `02_Knowledge`.
- [x] Change signal = hash of extracted text, not raw bytes → second `--refresh` of an unchanged episode reports `unchanged` (no re-write, no re-extract).
- [x] Polite: UA, inter-request delay, single retry, byte cap, `--limit`.
- [x] `fetch-*` without `--allow-network` still refuse (exit 2).

## Phase 2+ (later)

- [ ] `extract --allow-llm` writes schema-valid `data/extracts/epNN.json`.
- [ ] One cycle = at most one commit; "no material change" leaves repo clean.

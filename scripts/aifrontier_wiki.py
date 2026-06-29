#!/usr/bin/env python3
"""Deterministic, local-first CLI for the AI Frontier wiki.

Phase 0 scaffold. Network and LLM stages are explicit opt-ins and are NOT
implemented yet; they refuse to run. Deterministic stages that work today:
  validate, build-keyword-index, render-wiki, selfcheck.

Invariant enforced by design: canonical `2.wiki/` is a pure function of
canonical `data/extracts/*.json`. Demo/preview renders never touch canonical
output, data, or state. `validate` reconciles data, state, and rendered pages.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import escape, unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
EXTRACTS_DIR = DATA / "extracts"
WIKI = ROOT / "2.wiki"
PREVIEW = ROOT / "preview"
ASSETS_REL_DEEP = "../../assets"   # from <out>/episodes|keywords/*.html
ASSETS_REL_TOP = "../assets"       # from <out>/*.html

# Bulky originals live OUTSIDE the repo, in 06_Artifacts (per operating rules).
ARTIFACT_ROOT = Path.home() / "BaseCamp" / "06_Artifacts" / "aifrontier-wiki"
RAW_ROOT = ARTIFACT_ROOT / "raw"
JOBS_DIR = ARTIFACT_ROOT / "extract-jobs"

# Phase 2 extraction config (overridable via config/local.env -> environment).
EXTRACT_MAX_CHARS = int(os.environ.get("AIFRONTIER_EXTRACT_MAX_CHARS", "80000"))
EXTRACT_ADAPTERS = ("noop", "prompt_export", "openai_compatible", "deepseek")

# Polite fetch configuration (overridable via config/local.env -> environment).
FETCH_UA = os.environ.get("AIFRONTIER_FETCH_USER_AGENT", "aifrontier-wiki/phase1 personal-research")
FETCH_DELAY = float(os.environ.get("AIFRONTIER_FETCH_DELAY_SECONDS", "2"))
FETCH_TIMEOUT = 30
FETCH_MAX_BYTES = 3_000_000
KO_EP_RE = re.compile(r"/ko/episodes/ep(\d+)/?$")

TYPE_LABEL = {"concept": "개념", "person": "인물", "model": "모델"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Minimal JSON-Schema-subset validator (stdlib only).
# Supports: type, required, properties, items, enum, pattern (subset enough
# for the schemas in data/). Ignores $schema/title/additionalProperties.
# --------------------------------------------------------------------------- #
def _type_ok(inst, t) -> bool:
    for tt in (t if isinstance(t, list) else [t]):
        if tt == "string" and isinstance(inst, str):
            return True
        if tt == "integer" and isinstance(inst, int) and not isinstance(inst, bool):
            return True
        if tt == "number" and isinstance(inst, (int, float)) and not isinstance(inst, bool):
            return True
        if tt == "object" and isinstance(inst, dict):
            return True
        if tt == "array" and isinstance(inst, list):
            return True
        if tt == "boolean" and isinstance(inst, bool):
            return True
        if tt == "null" and inst is None:
            return True
    return False


def schema_errors(inst, schema, path="$"):
    errs = []
    t = schema.get("type")
    if t is not None and not _type_ok(inst, t):
        errs.append(f"{path}: expected type {t}, got {type(inst).__name__}")
        return errs
    if "enum" in schema and inst not in schema["enum"]:
        errs.append(f"{path}: {inst!r} not in enum {schema['enum']}")
    if "pattern" in schema and isinstance(inst, str) and not re.search(schema["pattern"], inst):
        errs.append(f"{path}: {inst!r} does not match pattern {schema['pattern']}")
    if isinstance(inst, dict):
        for req in schema.get("required", []):
            if req not in inst:
                errs.append(f"{path}: missing required '{req}'")
        for k, sub in schema.get("properties", {}).items():
            if k in inst:
                errs += schema_errors(inst[k], sub, f"{path}.{k}")
    if isinstance(inst, list) and "items" in schema:
        for i, item in enumerate(inst):
            errs += schema_errors(item, schema["items"], f"{path}[{i}]")
    return errs


# --------------------------------------------------------------------------- #
# Core: wrap body occurrences with keyword anchors + count per keyword.
# --------------------------------------------------------------------------- #
def wrap_body(paragraphs, entities):
    """Return (list_of_paragraph_html, counts{kw_id: n}).

    Each occurrence becomes <mark class="term" id="{id}-{n}" data-kw="{id}">.
    Aliases are matched longest-first; overlapping matches are dropped.
    """
    aliases = []
    for ent in entities:
        for form in (ent.get("aliases") or [ent["label"]]):
            if form:
                aliases.append((form, ent["id"]))
    aliases.sort(key=lambda x: len(x[0]), reverse=True)

    counts = {}
    html_paras = []
    for para in paragraphs:
        matches = []
        for surface, kid in aliases:
            start = 0
            while True:
                pos = para.find(surface, start)
                if pos < 0:
                    break
                matches.append((pos, pos + len(surface), kid, surface))
                start = pos + len(surface)
        matches.sort(key=lambda m: (m[0], -(m[1] - m[0])))
        chosen, last_end = [], -1
        for m in matches:
            if m[0] >= last_end:
                chosen.append(m)
                last_end = m[1]
        out, cur = [], 0
        for (s, e, kid, surf) in chosen:
            out.append(escape(para[cur:s]))
            counts[kid] = counts.get(kid, 0) + 1
            out.append(f'<mark class="term" id="{kid}-{counts[kid]}" data-kw="{escape(kid)}">{escape(surf)}</mark>')
            cur = e
        out.append(escape(para[cur:]))
        html_paras.append("<p>" + "".join(out) + "</p>")
    return html_paras, counts


def load_extracts(extra_paths=None):
    extracts = []
    for p in sorted(glob.glob(str(EXTRACTS_DIR / "*.json"))):
        extracts.append(load_json(Path(p)))
    for ep in extra_paths or []:
        extracts.append(load_json(Path(ep)))
    by_id = {}
    for ex in extracts:
        by_id[ex["ep_id"]] = ex
    return [by_id[k] for k in sorted(by_id)]


def build_index(extracts):
    index = {}
    for ex in extracts:
        _, counts = wrap_body(ex.get("body_paragraphs", []), ex.get("entities", []))
        ent_by_id = {e["id"]: e for e in ex.get("entities", [])}
        for kid, n in counts.items():
            ent = ent_by_id.get(kid, {"label": kid, "type": "concept"})
            slot = index.setdefault(kid, {"id": kid, "label": ent["label"], "type": ent.get("type", "concept"), "total": 0, "eps": []})
            slot["total"] += n
            slot["eps"].append({"ep_id": ex["ep_id"], "count": n, "first_anchor": f"{kid}-1"})
    keywords = sorted(index.values(), key=lambda k: (-k["total"], k["label"]))
    return {"schema_version": "1.0", "generated_at": now_iso(), "keywords": keywords}


def index_signature(index):
    """Order-independent signature for consistency comparison."""
    sig = []
    for k in sorted(index["keywords"], key=lambda x: x["id"]):
        eps = sorted((e["ep_id"], e["count"], e["first_anchor"]) for e in k["eps"])
        sig.append((k["id"], k["label"], k["type"], k["total"], tuple(eps)))
    return sig


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #
def page_shell(title, assets_rel, body_html):
    return (
        "<!doctype html>\n<html lang=\"ko\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{escape(title)}</title>\n"
        f"<link rel=\"stylesheet\" href=\"{assets_rel}/styles/wiki.css\">\n</head>\n<body>\n<main>\n"
        + body_html
        + f"\n</main>\n<script src=\"{assets_rel}/wiki.js\"></script>\n</body>\n</html>\n"
    )


def render_episode(ex, index_keywords):
    ep = ex["ep_id"]
    by_kw = {k["id"]: k for k in index_keywords}
    body_paras, _ = wrap_body(ex.get("body_paragraphs", []), ex.get("entities", []))
    meta = " · ".join([f"{ex.get('published_date','')}"] + ex.get("hosts", []))
    p = []
    p.append(f'<p class="ep-cat">AI Frontier 위키 · {escape(ex.get("category") or "")}</p>')
    p.append(f'<p class="ep-meta"><span class="epn">EP {ep}</span> {escape(meta)}</p>')
    p.append(f"<h1>{escape(ex['title'])}</h1>")
    p.append(f'<blockquote class="one-line">{escape(ex["one_line"])}</blockquote>')
    if ex.get("key_points"):
        p.append("<h2>핵심 포인트</h2>")
        p.append('<ul class="key-points">' + "".join(f"<li>{escape(x)}</li>" for x in ex["key_points"]) + "</ul>")
    if ex.get("flow"):
        items = "".join(f'<div class="flow-item"><span class="stage">{escape(f["stage"])}</span><p>{escape(f["summary"])}</p></div>' for f in ex["flow"])
        p.append("<h2>다룬 흐름</h2>")
        p.append(f'<div class="flow">{items}</div>')
    p.append("<h2>본문 엑기스</h2>")
    p.append(f'<div id="afw-body">{"".join(body_paras)}</div>')
    p.append("<h2>등장 개념 · 인물 · 모델</h2>")
    p.append('<p class="entities-hint">키워드를 누르면 등장 에피소드와 본문 위치로 이동합니다</p>')
    chips = "".join(f'<button class="kwchip kw-{e.get("type","concept")}" data-kw="{escape(e["id"])}">{escape(e["label"])}</button>' for e in ex.get("entities", []))
    p.append(f'<div id="afw-chips">{chips}</div>')
    p.append(
        '<div id="afw-panel" class="panel"><div class="panel-head">'
        '<span><span id="afw-kwname"></span> <span class="muted">— 등장 에피소드</span></span></div>'
        '<div id="afw-eplist" class="eplist"></div><p id="afw-note" class="note"></p></div>'
    )
    # Floating keyword explorer: pick a keyword (combo) + step through its body
    # occurrences. Fixed to the right, visible while scrolling.
    p.append(
        '<div id="afw-float" role="navigation" aria-label="키워드 탐색">'
        '<div class="ff-head"><span class="ff-title">키워드</span>'
        '<button id="afw-clear" class="fclear" aria-label="키워드 해제" title="해제 (Esc)">×</button></div>'
        '<select id="afw-kwselect" class="ff-select" aria-label="키워드 선택"><option value="">키워드 선택…</option></select>'
        '<div class="ff-nav">'
        '<button id="afw-prev" class="fbtn" aria-label="이전 등장" title="이전 등장">↑</button>'
        '<span id="afw-count" class="fcount">—</span>'
        '<button id="afw-next" class="fbtn" aria-label="다음 등장" title="다음 등장">↓</button></div></div>'
    )
    if ex.get("notable_quote"):
        q = ex["notable_quote"]
        spk = f' <span class="muted">— {escape(q["speaker"])}</span>' if q.get("speaker") else ""
        p.append(f'<blockquote class="quote">“{escape(q["text"])}”{spk}</blockquote>')
    src_html = "<h2>출처 · 원문</h2><div class=\"sources\">"
    if ex.get("source_url"):
        src_html += f'<div>↪ <a href="{escape(ex["source_url"])}">{escape(ex["source_url"])}</a></div>'
    if ex.get("raw_path"):
        src_html += f'<div class="muted">archive: <code>{escape(ex["raw_path"])}</code></div>'
    src_html += "</div>"
    p.append(src_html)
    status = ex.get("review_status", "draft")
    p.append(
        f'<div class="ep-footer"><span class="badge {"draft" if status == "draft" else ""}">{escape(status)}</span>'
        f'<span>{escape(ex.get("extractor") or "")} · 추출 {escape(ex.get("extracted_at") or "")}</span></div>'
    )
    kwdata = {"ep_id": ep, "keywords": {}}
    for e in ex.get("entities", []):
        slot = by_kw.get(e["id"])
        eps = [{"ep": r["ep_id"], "c": r["count"], "cur": r["ep_id"] == ep} for r in (slot["eps"] if slot else [])]
        kwdata["keywords"][e["id"]] = {"label": e["label"], "type": e.get("type", "concept"), "eps": eps}
    p.append('<script type="application/json" id="afw-data">' + json.dumps(kwdata, ensure_ascii=False) + "</script>")
    return page_shell(f"EP{ep} · {ex['title']}", ASSETS_REL_DEEP, "\n".join(p))


def render_index(extracts, index_keywords):
    eps = sorted(extracts, key=lambda e: e["ep_id"], reverse=True)
    p = []
    p.append('<div class="site-head"><span class="site-title">AI Frontier 위키</span></div>')
    p.append(f'<p class="muted">aifrontier.kr 한국어 에피소드 엑기스 · 갱신 {today()}</p>')
    p.append('<div class="stats">')
    p.append(f'<div class="stat"><p class="l">에피소드</p><p class="v">{len(eps)}</p></div>')
    p.append(f'<div class="stat"><p class="l">키워드</p><p class="v">{len(index_keywords)}</p></div>')
    p.append('<div class="stat"><p class="l">추출 모델</p><p class="v" style="font-size:15px">DeepSeek Pro</p></div>')
    p.append("</div>")
    p.append('<p class="crumb"><a href="keywords/index.html">키워드 인덱스 →</a></p>')
    cards = []
    for e in eps:
        tags = "".join(f'<span class="kwchip kw-{ent.get("type","concept")}" style="font-size:11px">{escape(ent["label"])}</span>' for ent in e.get("entities", [])[:3])
        cards.append(
            f'<a class="epcard" href="episodes/ep{e["ep_id"]}.html">'
            f'<span class="h"><span class="epn">EP {e["ep_id"]}</span> <span class="muted">{escape(e.get("published_date") or "")}</span></span>'
            f'<div class="ttl">{escape(e["title"])}</div>'
            f'<p class="ol">{escape(e["one_line"])}</p>'
            f'<div class="taglist" style="margin-top:8px">{tags}</div></a>'
        )
    p.append('<div class="epcards">' + ("".join(cards) if cards else '<p class="muted">아직 추출된 에피소드가 없습니다.</p>') + "</div>")
    return page_shell("AI Frontier 위키", ASSETS_REL_TOP, "\n".join(p))


def render_keywords_page(index_keywords):
    total_eps = len({r["ep_id"] for k in index_keywords for r in k["eps"]})
    top = index_keywords[0]["label"] if index_keywords else "-"
    top_n = index_keywords[0]["total"] if index_keywords else 0
    p = []
    p.append('<p class="crumb"><a href="../index.html">← 위키 홈</a></p>')
    p.append('<div class="site-head"><span class="site-title">키워드</span></div>')
    p.append('<p class="muted">전체에서 추출된 개념 · 인물 · 모델 색인</p>')
    p.append('<div class="stats">')
    p.append(f'<div class="stat"><p class="l">키워드</p><p class="v">{len(index_keywords)}</p></div>')
    p.append(f'<div class="stat"><p class="l">에피소드</p><p class="v">{total_eps}</p></div>')
    p.append(f'<div class="stat"><p class="l">최다 등장</p><p class="v" style="font-size:15px">{escape(top)} <span class="muted">{top_n}회</span></p></div>')
    p.append("</div>")
    p.append('<input id="afk-q" type="text" placeholder="키워드 검색">')
    p.append('<div id="afk-groups"></div>')
    p.append(
        '<div id="afk-panel" class="panel"><div class="panel-head">'
        '<span><span id="afk-name"></span> <span id="afk-sub" class="muted"></span></span></div>'
        '<div id="afk-eplist" class="eplist"></div></div>'
    )
    p.append('<script type="application/json" id="afk-data">' + json.dumps(index_keywords, ensure_ascii=False) + "</script>")
    return page_shell("키워드 — AI Frontier 위키", ASSETS_REL_DEEP, "\n".join(p))


# --------------------------------------------------------------------------- #
# Managed output: canonical 2.wiki is a pure function of canonical extracts.
# --------------------------------------------------------------------------- #
def managed_pages(out_dir):
    pages = sorted(glob.glob(str(out_dir / "episodes" / "ep*.html")))
    for rel in ("index.html", "keywords/index.html"):
        pp = out_dir / rel
        if pp.exists():
            pages.append(str(pp))
    return pages


def clean_managed(out_dir):
    for pth in managed_pages(out_dir):
        Path(pth).unlink()


def render_to(out_dir, extracts, index_keywords):
    (out_dir / "episodes").mkdir(parents=True, exist_ok=True)
    (out_dir / "keywords").mkdir(parents=True, exist_ok=True)
    clean_managed(out_dir)
    for ex in extracts:
        (out_dir / "episodes" / f"ep{ex['ep_id']}.html").write_text(render_episode(ex, index_keywords), encoding="utf-8")
    (out_dir / "index.html").write_text(render_index(extracts, index_keywords), encoding="utf-8")
    (out_dir / "keywords" / "index.html").write_text(render_keywords_page(index_keywords), encoding="utf-8")


def rendered_ep_ids(out_dir):
    ids = []
    for pth in glob.glob(str(out_dir / "episodes" / "ep*.html")):
        m = re.match(r"ep(\d+)\.html$", Path(pth).name)
        if m:
            ids.append(int(m.group(1)))
    return sorted(ids)


def update_state(extracts, index_keywords, run_id):
    episodes_doc = load_json(DATA / "episodes.json") if (DATA / "episodes.json").exists() else {"episodes": []}
    cur = load_json(ROOT / "state/current-state.json")
    cur["anchor_date"] = today()
    cur["counts"] = {
        "episodes_discovered": len(episodes_doc.get("episodes", [])),
        "episodes_fetched": len(episodes_doc.get("episodes", [])),
        "episodes_extracted": len(extracts),
        "episodes_rendered": len(extracts),
        "keywords": len(index_keywords),
    }
    cur["last_run_id"] = run_id
    dump_json(ROOT / "state/current-state.json", cur)
    rs = load_json(ROOT / "state/run-status.json")
    rs["run_id"] = run_id
    rs["run_status"] = "success"
    rs["finished_at"] = now_iso()
    rs["stage_statuses"]["render_wiki"] = "success"
    rs["stage_statuses"]["build_keyword_index"] = "success"
    rs["user_facing_summary"] = {"language": "ko", "text": f"로컬 렌더 완료: 에피소드 {len(extracts)}개, 키워드 {len(index_keywords)}개."}
    dump_json(ROOT / "state/run-status.json", rs)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
REQUIRED_FILES = [
    "6.README.md", "3.sources.md",
    "1.specs/design.md", "1.specs/html-information-architecture.md", "1.specs/validation-checklist.md",
    "data/episodes.schema.json", "data/extract.schema.json", "data/keyword-index.schema.json",
    "data/episodes.json",
    "state/run-status.json", "state/current-state.json", "state/scheduler-state.json", "state/change-history.jsonl",
    "assets/styles/wiki.css", "assets/wiki.js",
    "0.prompt/extract-prompt.md", "0.prompt/prompt.md",
]


def collect_problems():
    problems = []
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            problems.append(f"missing file: {rel}")

    def try_load(rel):
        try:
            return load_json(ROOT / rel)
        except Exception as e:
            problems.append(f"invalid json: {rel}: {e}")
            return None

    # JSON parses
    for rel in ["data/episodes.json", "data/keyword-index.json",
                "state/run-status.json", "state/current-state.json", "state/scheduler-state.json"]:
        if (ROOT / rel).exists():
            try_load(rel)

    # scheduler safety
    sched = ROOT / "state/scheduler-state.json"
    if sched.exists():
        st = load_json(sched)
        if st.get("enabled") is True:
            problems.append("scheduler-state.enabled is true (Phase 0 expects false)")

    # --- schema enforcement -------------------------------------------------
    ep_schema = load_json(DATA / "episodes.schema.json")
    ex_schema = load_json(DATA / "extract.schema.json")
    kw_schema = load_json(DATA / "keyword-index.schema.json")
    if (DATA / "episodes.json").exists():
        for e in schema_errors(load_json(DATA / "episodes.json"), ep_schema, "episodes.json"):
            problems.append("schema: " + e)
    if (DATA / "keyword-index.json").exists():
        for e in schema_errors(load_json(DATA / "keyword-index.json"), kw_schema, "keyword-index.json"):
            problems.append("schema: " + e)

    extracts = []
    kw_identity = {}  # id -> (label, type) for stability check
    for pth in sorted(glob.glob(str(EXTRACTS_DIR / "*.json"))):
        name = Path(pth).name
        try:
            ex = load_json(Path(pth))
        except Exception as e:
            problems.append(f"invalid extract {name}: {e}")
            continue
        for e in schema_errors(ex, ex_schema, name):
            problems.append("schema: " + e)
        # filename must match ep_id
        m = re.match(r"ep(\d+)\.json$", name)
        if m and ex.get("ep_id") != int(m.group(1)):
            problems.append(f"{name}: filename ep id != ep_id field ({ex.get('ep_id')})")
        # unique entity ids within an episode
        ids = [en.get("id") for en in ex.get("entities", [])]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            problems.append(f"{name}: duplicate entity id(s): {sorted(dupes)}")
        # stable (label,type) per keyword id across episodes
        for en in ex.get("entities", []):
            key = en.get("id")
            ident = (en.get("label"), en.get("type"))
            if key in kw_identity and kw_identity[key] != ident:
                problems.append(f"keyword '{key}': inconsistent label/type {kw_identity[key]} vs {ident} ({name})")
            else:
                kw_identity.setdefault(key, ident)
        extracts.append(ex)

    # unique ep_id across extracts
    ep_ids = [ex.get("ep_id") for ex in extracts]
    dup_ep = {i for i in ep_ids if ep_ids.count(i) > 1}
    if dup_ep:
        problems.append(f"duplicate ep_id across extracts: {sorted(dup_ep)}")

    canonical = load_extracts()  # de-duped canonical set
    index = build_index(canonical)

    # --- consistency: keyword-index.json matches recomputed -----------------
    if (DATA / "keyword-index.json").exists():
        on_disk = load_json(DATA / "keyword-index.json")
        if index_signature(on_disk) != index_signature(index):
            problems.append("keyword-index.json is stale: does not match data/extracts (run build-keyword-index)")

    # --- consistency: no orphan rendered pages ------------------------------
    canon_ids = {ex["ep_id"] for ex in canonical}
    for ep in rendered_ep_ids(WIKI):
        if ep not in canon_ids:
            problems.append(f"orphan rendered page: 2.wiki/episodes/ep{ep}.html has no canonical extract")

    # --- consistency: current-state counts match reality --------------------
    cur = load_json(ROOT / "state/current-state.json")
    c = cur.get("counts", {})
    if c.get("episodes_extracted") != len(canonical):
        problems.append(f"current-state episodes_extracted={c.get('episodes_extracted')} != actual {len(canonical)}")
    if c.get("episodes_rendered") != len(rendered_ep_ids(WIKI)):
        problems.append(f"current-state episodes_rendered={c.get('episodes_rendered')} != actual {len(rendered_ep_ids(WIKI))}")
    if c.get("keywords") != len(index["keywords"]):
        problems.append(f"current-state keywords={c.get('keywords')} != actual {len(index['keywords'])}")

    return problems, canonical, index


def cmd_validate(args) -> int:
    problems, canonical, index = collect_problems()
    if problems:
        print("VALIDATE: FAIL")
        for pr in problems:
            print("  - " + pr)
        return 1
    print("VALIDATE: PASS")
    print(f"  files ok · schemas ok · invariants ok · state reconciled · {len(canonical)} extract(s), {len(index['keywords'])} keyword(s)")
    return 0


def cmd_build_keyword_index(args) -> int:
    extracts = load_extracts()
    index = build_index(extracts)
    dump_json(DATA / "keyword-index.json", index)
    print(f"build-keyword-index: {len(index['keywords'])} keyword(s) from {len(extracts)} extract(s) -> data/keyword-index.json")
    return 0


def cmd_render_wiki(args) -> int:
    extra = args.demo_fixture or []
    if extra:
        # Preview/demo: NEVER touch canonical output, data, or state.
        print("NOTE: demo render -> preview/ (SAMPLE content; canonical 2.wiki, data, state untouched):")
        for e in extra:
            print("  - " + e)
        extracts = load_extracts(extra)
        index = build_index(extracts)
        render_to(PREVIEW, extracts, index["keywords"])
        print(f"render-wiki(demo): {len(extracts)} page(s), {len(index['keywords'])} keyword(s) -> preview/")
        return 0
    # Canonical: pure function of data/extracts.
    extracts = load_extracts()
    index = build_index(extracts)
    dump_json(DATA / "keyword-index.json", index)
    render_to(WIKI, extracts, index["keywords"])
    update_state(extracts, index["keywords"], run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    print(f"render-wiki: {len(extracts)} episode page(s), {len(index['keywords'])} keyword(s) -> 2.wiki/ (state reconciled)")
    return 0


def cmd_selfcheck(args) -> int:
    """Regression guard: render canonical extracts to a throwaway dir and
    confirm the renderer is complete (one page per extract, indexes present)
    and the keyword index is stable. Touches nothing canonical."""
    extracts = load_extracts()
    index = build_index(extracts)
    tmp = Path(tempfile.mkdtemp(prefix="afw-selfcheck-"))
    try:
        render_to(tmp, extracts, index["keywords"])
        pages = rendered_ep_ids(tmp)
        expected = sorted(ex["ep_id"] for ex in extracts)
        problems = []
        if pages != expected:
            problems.append(f"rendered pages {pages} != extracts {expected}")
        if not (tmp / "index.html").exists():
            problems.append("index.html not rendered")
        if not (tmp / "keywords" / "index.html").exists():
            problems.append("keywords/index.html not rendered")
        if index_signature(build_index(extracts)) != index_signature(index):
            problems.append("keyword index not deterministic")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if problems:
        print("SELFCHECK: FAIL")
        for pr in problems:
            print("  - " + pr)
        return 1
    print(f"SELFCHECK: PASS ({len(extracts)} extract(s) -> {len(extracts)} page(s), renderer complete & deterministic)")
    return 0


# --------------------------------------------------------------------------- #
# Phase 1: polite network collection (stdlib only). Opt-in via --allow-network.
# --------------------------------------------------------------------------- #
def http_get(url):
    """GET with UA, timeout, single retry, and a hard byte cap.
    Returns (status_code, body_bytes, final_url)."""
    req = urllib.request.Request(url, headers={"User-Agent": FETCH_UA, "Accept-Language": "ko"})
    last = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
                data = r.read(FETCH_MAX_BYTES + 1)
                if len(data) > FETCH_MAX_BYTES:
                    raise ValueError(f"response exceeds {FETCH_MAX_BYTES} bytes")
                return getattr(r, "status", 200), data, r.geturl()
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            last = e
            if attempt == 0:
                time.sleep(FETCH_DELAY)
    raise last


def html_to_text(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</(p|div|li|h[1-6]|section|article)>", "\n", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_title(html):
    m = re.search(r'(?is)<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']', html)
    if not m:
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not m:
        return None
    t = unescape(m.group(1)).strip()
    t = re.split(r"\s*[|·\-–—]\s*AI ?Frontier", t)[0].strip()
    return t or None


def extract_date(html):
    for pat in (r'"datePublished"\s*:\s*"([0-9]{4}-[0-9]{2}-[0-9]{2})',
                r'(?is)<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([0-9]{4}-[0-9]{2}-[0-9]{2})'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def update_fetch_counts(doc):
    cur = load_json(ROOT / "state/current-state.json")
    eps = doc.get("episodes", [])
    cur.setdefault("counts", {})
    cur["counts"]["episodes_discovered"] = len(eps)
    cur["counts"]["episodes_fetched"] = sum(1 for e in eps if e.get("status") in ("fetched", "extracted", "rendered"))
    dump_json(ROOT / "state/current-state.json", cur)


def _set_stage(stage, status):
    rs = load_json(ROOT / "state/run-status.json")
    rs["stage_statuses"][stage] = status
    rs["finished_at"] = now_iso()
    dump_json(ROOT / "state/run-status.json", rs)


def cmd_fetch_index(args):
    if not args.allow_network:
        print("fetch-index requires --allow-network (opt-in).")
        return 2
    doc = load_json(DATA / "episodes.json")
    sitemap = doc.get("source", {}).get("sitemap") or "https://aifrontier.kr/sitemap.xml"
    print(f"fetch-index: GET {sitemap}")
    try:
        _, data, _ = http_get(sitemap)
        root = ET.fromstring(data)
    except Exception as e:
        print(f"  error: {e}")
        _set_stage("fetch_index", "failed")
        return 1
    found = {}
    for el in root.iter():
        if el.tag.lower().endswith("loc") and el.text:
            m = KO_EP_RE.search(el.text.strip())
            if m:
                found[int(m.group(1))] = el.text.strip()
    existing = {e["ep_id"]: e for e in doc.get("episodes", [])}
    new_ids = []
    for ep_id, url in sorted(found.items()):
        if ep_id in existing:
            existing[ep_id]["url"] = url
            existing[ep_id]["last_seen"] = today()
        else:
            existing[ep_id] = {"ep_id": ep_id, "url": url, "title": None, "published_date": None,
                               "status": "discovered", "content_hash": None, "last_seen": today()}
            new_ids.append(ep_id)
    doc["episodes"] = [existing[k] for k in sorted(existing)]
    doc["updated_at"] = now_iso()
    dump_json(DATA / "episodes.json", doc)
    update_fetch_counts(doc)
    # Best-effort: snapshot the site's llms.txt corpus for Phase 2 extraction.
    site_dir = RAW_ROOT / "_site"
    for name in ("llms.txt", "llms-full.txt"):
        try:
            _, blob, _ = http_get(f"https://aifrontier.kr/{name}")
            site_dir.mkdir(parents=True, exist_ok=True)
            (site_dir / name).write_bytes(blob)
            print(f"  saved {name} ({len(blob)}B)")
            time.sleep(FETCH_DELAY)
        except Exception:
            pass
    _set_stage("fetch_index", "success")
    print(f"  found {len(found)} ko episode(s); new {len(new_ids)}; total {len(doc['episodes'])}")
    if new_ids:
        print("  new: " + ", ".join(f"ep{i}" for i in new_ids))
    return 0


def cmd_fetch_pages(args):
    if not args.allow_network:
        print("fetch-pages requires --allow-network (opt-in).")
        return 2
    doc = load_json(DATA / "episodes.json")
    eps = doc.get("episodes", [])
    targets = [e for e in eps if (args.refresh or e.get("status") == "discovered")][: max(0, args.limit)]
    if not targets:
        print("fetch-pages: nothing to fetch (no discovered episodes). Run fetch-index first, or use --refresh.")
        return 0
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    fetched = unchanged = failed = 0
    for e in targets:
        ep_id, url = e["ep_id"], e["url"]
        epdir = RAW_ROOT / f"ep{ep_id}"
        metap = epdir / "meta.json"
        try:
            status, data, final = http_get(url)
        except Exception as ex:
            failed += 1
            print(f"  ep{ep_id}: FAIL {ex}")
            continue
        html = data.decode("utf-8", "replace")
        text = html_to_text(html)
        # Change signal = hash of EXTRACTED TEXT, not raw bytes: the site embeds a
        # per-render nonce/build-id in <script> (stripped by html_to_text), so a
        # raw-bytes hash would flip every fetch and force needless re-extraction.
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if metap.exists() and not args.force and load_json(metap).get("content_hash") == h:
            unchanged += 1
            e["last_seen"] = today()
            print(f"  ep{ep_id}: unchanged")
            time.sleep(FETCH_DELAY)
            continue
        epdir.mkdir(parents=True, exist_ok=True)
        (epdir / "page.html").write_text(html, encoding="utf-8")
        (epdir / "text.txt").write_text(text, encoding="utf-8")
        nd = re.search(r'(?is)<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
        if nd:
            try:
                (epdir / "next-data.json").write_text(
                    json.dumps(json.loads(nd.group(1)), ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        title, date = extract_title(html), extract_date(html)
        dump_json(metap, {"ep_id": ep_id, "url": url, "final_url": final, "status_code": status,
                          "fetched_at": now_iso(), "content_hash": h,
                          "raw_hash": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                          "text_length": len(text), "title": title, "published_date": date})
        e["status"] = "fetched"
        e["content_hash"] = h
        e["last_seen"] = today()
        if title and not e.get("title"):
            e["title"] = title
        if date and not e.get("published_date"):
            e["published_date"] = date
        fetched += 1
        print(f"  ep{ep_id}: fetched ({len(data)}B, text {len(text)} chars)" + (" [thin]" if len(text) < 400 else ""))
        time.sleep(FETCH_DELAY)
    doc["episodes"] = eps
    doc["updated_at"] = now_iso()
    dump_json(DATA / "episodes.json", doc)
    update_fetch_counts(doc)
    _set_stage("fetch_pages", "success" if failed == 0 else "partial_success")
    print(f"fetch-pages: fetched {fetched}, unchanged {unchanged}, failed {failed}; raw -> {RAW_ROOT}")
    return 0 if failed == 0 else 1


# --------------------------------------------------------------------------- #
# Phase 2: extraction input assembly + adapters.
# Deterministic plumbing (input assembly, prompt_export, output validation) is
# done here; the LLM call (openai_compatible/deepseek) is opt-in and run by
# Hermes + DeepSeek Pro. See 1.specs/phase-2-extraction-runbook.md.
# --------------------------------------------------------------------------- #
def read_llms_sections():
    """Parse raw/_site/llms-full.txt into {ep_id: section_markdown}."""
    path = RAW_ROOT / "_site" / "llms-full.txt"
    if not path.exists():
        return {}
    full = path.read_text(encoding="utf-8", errors="replace")
    sections = {}
    cur_id, buf = None, []
    for line in full.splitlines():
        m = re.match(r"^##\s+EP\s+(\d+):", line)
        if m:
            if cur_id is not None:
                sections[cur_id] = "\n".join(buf).strip()
            cur_id, buf = int(m.group(1)), [line]
        elif cur_id is not None:
            buf.append(line)
    if cur_id is not None:
        sections[cur_id] = "\n".join(buf).strip()
    return sections


def transcript_from_text(text, hosts):
    """Slice the spoken transcript out of the page text (drop nav + chapter list).
    Transcript starts where a host first speaks at 00:00."""
    sliced = None
    for h in hosts or []:
        m = re.search(r"\b0?0:00\b\s*" + re.escape(h), text)
        if m:
            sliced = text[m.start():]
            break
    if sliced is None:
        m = re.search(r"\n\s*0?0:00\s+\S", text)
        sliced = text[m.start():] if m else text
    # drop the trailing site footer / prev-next navigation
    for marker in ("\n ← 이전", "\n← 이전", "← 이전", "© 20"):
        idx = sliced.find(marker)
        if idx != -1:
            sliced = sliced[:idx]
            break
    return sliced.strip()


def build_payload(ep_id):
    """Assemble the user-content payload for one episode (clean metadata +
    chapters from llms-full, transcript from text.txt)."""
    epdir = RAW_ROOT / f"ep{ep_id}"
    meta = load_json(epdir / "meta.json") if (epdir / "meta.json").exists() else {}
    section = read_llms_sections().get(ep_id, "")
    text = (epdir / "text.txt").read_text(encoding="utf-8", errors="replace") if (epdir / "text.txt").exists() else ""
    hosts = []
    mh = re.search(r"(?m)^- Hosts:\s*(.+)$", section)
    if mh:
        hosts = [h.strip() for h in re.split(r"[,/·]", mh.group(1)) if h.strip()]
    transcript = transcript_from_text(text, hosts)
    truncated = ""
    if len(transcript) > EXTRACT_MAX_CHARS:
        transcript = transcript[:EXTRACT_MAX_CHARS]
        truncated = "\n\n[... 트랜스크립트 일부 생략 (길이 제한) ...]"
    return (
        f"## 에피소드 메타데이터\n"
        f"- ep_id: {ep_id}\n"
        f"- title: {meta.get('title') or ''}\n"
        f"- published_date: {meta.get('published_date') or ''}\n"
        f"- source_url: {meta.get('url') or ''}\n"
        f"- raw_path: 06_Artifacts/aifrontier-wiki/raw/ep{ep_id}/page.html\n\n"
        f"## 구조화된 요약 (llms-full.txt)\n{section}\n\n"
        f"## 전사(transcript)\n{transcript}{truncated}\n"
    )


def system_prompt():
    return (ROOT / "0.prompt" / "extract-prompt.md").read_text(encoding="utf-8")


def build_messages(ep_id):
    return [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": build_payload(ep_id)},
    ]


def extract_problems(obj, ep_id):
    schema = load_json(DATA / "extract.schema.json")
    errs = ["schema: " + e for e in schema_errors(obj, schema, "extract")]
    if obj.get("ep_id") != ep_id:
        errs.append(f"ep_id mismatch: payload {ep_id} vs output {obj.get('ep_id')}")
    ids = [e.get("id") for e in obj.get("entities", [])]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errs.append(f"duplicate entity id(s): {sorted(dupes)}")
    return errs


def write_extract(obj, ep_id):
    problems = extract_problems(obj, ep_id)
    if problems:
        return problems
    dump_json(EXTRACTS_DIR / f"ep{ep_id}.json", obj)
    doc = load_json(DATA / "episodes.json")
    for e in doc.get("episodes", []):
        if e["ep_id"] == ep_id:
            e["status"] = "extracted"
    dump_json(DATA / "episodes.json", doc)
    return []


def http_post_json(url, payload, api_key=None, timeout=180):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": FETCH_UA}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def extract_targets(args):
    doc = load_json(DATA / "episodes.json")
    eps = doc.get("episodes", [])
    if args.episode:
        return [e for e in eps if e["ep_id"] == args.episode]
    pending = []
    for e in eps:
        if e.get("status") not in ("fetched", "extracted", "rendered"):
            continue
        already = (EXTRACTS_DIR / f"ep{e['ep_id']}.json").exists()
        if already and not args.force:
            continue
        pending.append(e)
    return pending[: max(0, args.limit)]


def cmd_extract(args):
    if args.adapter not in EXTRACT_ADAPTERS:
        print(f"unknown adapter: {args.adapter} (choose from {EXTRACT_ADAPTERS})")
        return 2
    targets = extract_targets(args)
    if not targets:
        print("extract: nothing to do (no fetched episodes pending, or all already extracted; use --force/--episode).")
        return 0

    if args.adapter == "prompt_export":
        # Deterministic: write ready-to-run jobs for DeepSeek/Hermes. No LLM.
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        for e in targets:
            ep_id = e["ep_id"]
            msgs = build_messages(ep_id)
            (JOBS_DIR / f"ep{ep_id}.messages.json").write_text(
                json.dumps({"ep_id": ep_id, "response_format": "json_object",
                            "output_path": f"data/extracts/ep{ep_id}.json", "messages": msgs},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            (JOBS_DIR / f"ep{ep_id}.prompt.md").write_text(
                f"# Extract job — EP {ep_id}\n\n"
                f"결과를 `data/extracts/ep{ep_id}.json` 에 **단일 JSON 객체**로 저장한다 "
                f"(스키마: `data/extract.schema.json`).\n\n"
                f"---\n\n## SYSTEM\n\n{msgs[0]['content']}\n\n---\n\n## INPUT\n\n{msgs[1]['content']}\n",
                encoding="utf-8")
        print(f"extract(prompt_export): wrote {len(targets)} job(s) -> {JOBS_DIR}")
        print("  next: DeepSeek/Hermes runs each job and saves data/extracts/epNN.json (see 1.specs/phase-2-extraction-runbook.md)")
        return 0

    if args.adapter == "noop":
        for e in targets:
            build_messages(e["ep_id"])  # exercise assembly only
        print(f"extract(noop): assembled {len(targets)} payload(s); wrote nothing.")
        return 0

    # openai_compatible / deepseek: live LLM call (opt-in).
    if not args.allow_llm:
        print(f"extract --adapter {args.adapter} requires --allow-llm (opt-in).")
        return 2
    base = args.llm_base_url or os.environ.get("AIFRONTIER_LLM_BASE_URL")
    model = args.llm_model or os.environ.get("AIFRONTIER_LLM_MODEL") or "deepseek-pro"
    key = os.environ.get("AIFRONTIER_LLM_API_KEY") or None
    if not base:
        print("missing endpoint: set --llm-base-url or AIFRONTIER_LLM_BASE_URL (config/local.env).")
        return 2
    is_local = re.search(r"localhost|127\.0\.0\.1", base) is not None
    if not is_local and not key:
        print("non-local endpoint requires AIFRONTIER_LLM_API_KEY.")
        return 2
    ok = fail = 0
    for e in targets:
        ep_id = e["ep_id"]
        try:
            resp = http_post_json(base.rstrip("/") + "/chat/completions",
                                  {"model": model, "messages": build_messages(ep_id),
                                   "temperature": 0.2, "response_format": {"type": "json_object"}},
                                  api_key=key)
            obj = json.loads(resp["choices"][0]["message"]["content"])
        except Exception as ex:
            fail += 1
            print(f"  ep{ep_id}: FAIL {ex}")
            continue
        problems = write_extract(obj, ep_id)
        if problems:
            fail += 1
            print(f"  ep{ep_id}: INVALID output -> not written")
            for pr in problems[:5]:
                print("      " + pr)
            continue
        ok += 1
        print(f"  ep{ep_id}: extracted -> data/extracts/ep{ep_id}.json")
    _set_stage("extract", "success" if fail == 0 else "partial_success")
    print(f"extract({args.adapter}): ok {ok}, fail {fail}")
    return 0 if fail == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AI Frontier wiki CLI (Phase 0 scaffold)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="Validate files, schemas, invariants, and data/state/render consistency")
    sub.add_parser("build-keyword-index", help="Build data/keyword-index.json from data/extracts/*.json")
    sub.add_parser("selfcheck", help="Render canonical extracts to a temp dir and verify renderer completeness")
    r = sub.add_parser("render-wiki", help="Render canonical 2.wiki/ from extracts (or preview/ with --demo-fixture)")
    r.add_argument("--demo-fixture", action="append", help="Render a fixture into preview/ (SAMPLE; never canonical)")
    fi = sub.add_parser("fetch-index", help="[Phase 1] Refresh episodes.json from sitemap/llms.txt")
    fi.add_argument("--allow-network", action="store_true")
    fp = sub.add_parser("fetch-pages", help="[Phase 1] Download episode originals to 06_Artifacts")
    fp.add_argument("--allow-network", action="store_true")
    fp.add_argument("--limit", type=int, default=5)
    fp.add_argument("--refresh", action="store_true", help="Re-check already-fetched episodes too")
    fp.add_argument("--force", action="store_true", help="Re-write even if content hash is unchanged")
    ex = sub.add_parser("extract", help="[Phase 2] Assemble inputs / export jobs / run DeepSeek extraction")
    ex.add_argument("--adapter", default="prompt_export", choices=EXTRACT_ADAPTERS)
    ex.add_argument("--allow-llm", action="store_true", help="Required for openai_compatible/deepseek adapters")
    ex.add_argument("--limit", type=int, default=5)
    ex.add_argument("--episode", type=int, help="Target a single ep_id")
    ex.add_argument("--force", action="store_true", help="Re-extract even if data/extracts/epNN.json exists")
    ex.add_argument("--llm-base-url", help="OpenAI-compatible base URL (else AIFRONTIER_LLM_BASE_URL)")
    ex.add_argument("--llm-model", help="Model id (else AIFRONTIER_LLM_MODEL, default deepseek-pro)")
    args = parser.parse_args(argv)
    return {
        "validate": cmd_validate,
        "build-keyword-index": cmd_build_keyword_index,
        "selfcheck": cmd_selfcheck,
        "render-wiki": cmd_render_wiki,
        "fetch-index": cmd_fetch_index,
        "fetch-pages": cmd_fetch_pages,
        "extract": cmd_extract,
    }[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

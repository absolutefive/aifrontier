(function () {
  "use strict";
  var TYPES = [
    { k: "concept", t: "개념" },
    { k: "person", t: "인물" },
    { k: "model", t: "모델" }
  ];
  function readJSON(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  }
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  // ---------- Episode page mode ----------
  function initEpisode() {
    var body = document.getElementById("afw-body");
    var data = readJSON("afw-data");
    if (!body || !data) return;
    var kwmap = data.keywords || {};
    var panel = document.getElementById("afw-panel");
    var nameEl = document.getElementById("afw-kwname");
    var eplist = document.getElementById("afw-eplist");
    var countEl = document.getElementById("afw-count");
    var note = document.getElementById("afw-note");
    var floatEl = document.getElementById("afw-float");
    var labelEl = document.getElementById("afw-float-kw");
    var terms = [], idx = 0;

    function clearHl() {
      var all = body.querySelectorAll(".term");
      for (var i = 0; i < all.length; i++) all[i].classList.remove("hl", "current");
    }
    function goto(i) {
      if (!terms.length) return;
      idx = (i + terms.length) % terms.length;
      for (var j = 0; j < terms.length; j++) terms[j].classList.remove("current");
      terms[idx].classList.add("current");
      terms[idx].scrollIntoView({ behavior: "smooth", block: "center" });
      if (countEl) countEl.textContent = (idx + 1) + "/" + terms.length;
    }
    function deactivate() {
      clearHl();
      var chips = document.querySelectorAll(".kwchip");
      for (var i = 0; i < chips.length; i++) chips[i].classList.remove("active");
      if (floatEl) floatEl.classList.remove("show");
      if (panel) panel.style.display = "none";
      terms = [];
    }
    function activate(kw) {
      clearHl();
      var chips = document.querySelectorAll(".kwchip");
      for (var i = 0; i < chips.length; i++) chips[i].classList.toggle("active", chips[i].getAttribute("data-kw") === kw);
      terms = [].slice.call(body.querySelectorAll('.term[data-kw="' + kw + '"]'));
      for (var t = 0; t < terms.length; t++) terms[t].classList.add("hl");
      var info = kwmap[kw] || { label: kw, eps: [] };
      if (nameEl) nameEl.textContent = info.label || kw;
      if (labelEl) labelEl.textContent = info.label || kw;
      if (note) note.style.display = "none";
      eplist.innerHTML = "";
      (info.eps || []).forEach(function (e) {
        var right = '<span class="sec">' + e.c + '회 등장 <span class="muted">›</span></span>';
        var left = '<span><span class="epn">EP ' + e.ep + '</span>' + (e.cur ? ' <span class="cur">현재 글</span>' : '') + '</span>';
        if (e.cur) {
          var row = el("div", "eprow", left + right);
          row.addEventListener("click", function () { if (note) note.style.display = "none"; goto(0); });
          eplist.appendChild(row);
        } else {
          var a = el("a", "eprow", left + right);
          a.setAttribute("href", "../episodes/ep" + e.ep + ".html#" + kw + "-1");
          eplist.appendChild(a);
        }
      });
      if (panel) panel.style.display = "block";
      if (floatEl) floatEl.classList.add("show");
      goto(0);
    }
    var chips = document.querySelectorAll(".kwchip");
    for (var c = 0; c < chips.length; c++) {
      (function (chip) {
        chip.addEventListener("click", function () { activate(chip.getAttribute("data-kw")); });
      })(chips[c]);
    }
    var prev = document.getElementById("afw-prev"), next = document.getElementById("afw-next"), clr = document.getElementById("afw-clear");
    if (prev) prev.addEventListener("click", function () { goto(idx - 1); });
    if (next) next.addEventListener("click", function () { goto(idx + 1); });
    if (clr) clr.addEventListener("click", deactivate);
    document.addEventListener("keydown", function (e) {
      if (!floatEl || !floatEl.classList.contains("show")) return;
      if (e.key === "Escape") deactivate();
    });
  }

  // ---------- Keyword index page mode ----------
  function initIndex() {
    var groups = document.getElementById("afk-groups");
    var data = readJSON("afk-data");
    if (!groups || !data) return;
    var panel = document.getElementById("afk-panel");
    var nameEl = document.getElementById("afk-name");
    var subEl = document.getElementById("afk-sub");
    var eplist = document.getElementById("afk-eplist");

    function select(k, btn) {
      var all = groups.querySelectorAll(".kw");
      for (var i = 0; i < all.length; i++) all[i].classList.toggle("active", all[i] === btn);
      nameEl.textContent = "‘" + k.label + "’";
      subEl.textContent = k.eps.length + "개 에피소드 · " + k.total + "회 등장";
      eplist.innerHTML = "";
      k.eps.slice().sort(function (a, b) { return b.count - a.count; }).forEach(function (e) {
        var a = el("a", "eprow",
          '<span class="epn">EP ' + e.ep_id + '</span>' +
          '<span class="sec">' + e.count + '회 등장 <code class="muted">ep' + e.ep_id + '#' + e.first_anchor + '</code> ›</span>');
        a.setAttribute("href", "../episodes/ep" + e.ep_id + ".html#" + e.first_anchor);
        eplist.appendChild(a);
      });
      panel.style.display = "block";
    }

    TYPES.forEach(function (ty) {
      var items = data.filter(function (k) { return k.type === ty.k; })
        .sort(function (a, b) { return b.total - a.total; });
      if (!items.length) return;
      var title = el("p", "grp-title", ty.t); title.setAttribute("data-grp", ty.k);
      var cloud = el("div", "cloud"); cloud.setAttribute("data-grp", ty.k);
      items.forEach(function (k) {
        var b = el("button", "kw kw-" + ty.k, "<span>" + k.label + "</span><span class='n'>" + k.total + "</span>");
        b.setAttribute("data-label", k.label);
        b.addEventListener("click", function () { select(k, b); });
        cloud.appendChild(b);
      });
      groups.appendChild(title); groups.appendChild(cloud);
    });

    var q = document.getElementById("afk-q");
    if (q) q.addEventListener("input", function (e) {
      var v = e.target.value.trim().toLowerCase();
      TYPES.forEach(function (ty) {
        var cloud = groups.querySelector('.cloud[data-grp="' + ty.k + '"]');
        var title = groups.querySelector('.grp-title[data-grp="' + ty.k + '"]');
        if (!cloud) return;
        var any = false, btns = cloud.querySelectorAll(".kw");
        for (var i = 0; i < btns.length; i++) {
          var hit = btns[i].getAttribute("data-label").toLowerCase().indexOf(v) > -1;
          btns[i].style.display = hit ? "inline-flex" : "none";
          if (hit) any = true;
        }
        title.style.display = any ? "block" : "none";
        cloud.style.display = any ? "flex" : "none";
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { initEpisode(); initIndex(); });
  } else { initEpisode(); initIndex(); }
})();

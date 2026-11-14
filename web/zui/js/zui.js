/* Nexus ZUI — منطق الواجهة الموحدة (v1.61.0 — خطة التناغم ب3.1).
   تعاقد API: /api/chat SSE (plan → chunk → [DONE]) · /api/conversations ·
   /api/agents · /api/status · /api/council/debate · /api/traces · /api/monitor.
   أوفلاين بالكامل: بلا CDN ولا خطوط خارجية. */
"use strict";

/* ══ i18n — العربية أولًا ══ */
const I18N = {
  ar: {
    brand: "Nexus ZUI", brandSub: "واجهة البرمجة الموحدة",
    newChat: "محادثة جديدة", agent: "الوكيل", connecting: "يتصل…", online: "متصل",
    offline: "غير متصل", welcomeTitle: "بماذا أساعدك اليوم؟",
    welcomeSub: "اكتب هدفك البرمجي — يوجهه التوجيه العرقي للوكيل الأنسب، والمجلس لا يتدخل إلا عند العجز أو بطلبك.",
    send: "إرسال", hint: "الإجابات متدفقة عبر SSE — شارة الوكيل تظهر من أول حدث plan.",
    placeholder: "اكتب هدفك… (Enter للإرسال، Shift+Enter لسطر جديد)",
    tabAgents: "الوكلاء", tabCouncil: "المجلس", tabTraces: "التتبع", tabMonitor: "التقييم",
    you: "أنت", councilAsk: "اسأل المجلس", councilPlaceholder: "موضوع المداولة…",
    noTraces: "لا أحداث تتبع بعد.", noMonitor: "لا تقييمات — لا أحداث في سجل الأثر بعد.",
    agents: "الوكلاء المدمجون", fleetEval: "تقييم الأسطول من التتبع الحي",
    copy: "نسخ", copied: "نُسخ", sended: "يرسل…", emptyMsg: "اكتب رسالة أولًا.",
    loadFail: "تعذر التحميل", newConv: "محادثة بلا عنوان", convFail: "تعذر إنشاء المحادثة",
  },
  en: {
    brand: "Nexus ZUI", brandSub: "Unified Coding UI",
    newChat: "New chat", agent: "Agent", connecting: "connecting…", online: "online",
    offline: "offline", welcomeTitle: "How can I help today?",
    welcomeSub: "State your coding goal — raced routing picks the best agent, and the council only steps in on impasse or explicit request.",
    send: "Send", hint: "Answers stream over SSE — the agent badge appears on the first plan event.",
    placeholder: "Type your goal… (Enter to send, Shift+Enter for newline)",
    tabAgents: "Agents", tabCouncil: "Council", tabTraces: "Traces", tabMonitor: "Review",
    you: "You", councilAsk: "Ask the council", councilPlaceholder: "Debate topic…",
    noTraces: "No trace events yet.", noMonitor: "No evaluations — the trace log is empty.",
    agents: "Built-in agents", fleetEval: "Fleet evaluation from live traces",
    copy: "Copy", copied: "Copied", sended: "sending…", emptyMsg: "Type a message first.",
    loadFail: "Failed to load", newConv: "Untitled chat", convFail: "Failed to create chat",
  },
};
let LANG = localStorage.getItem("nexus_zui_lang") || "ar";

function t(key) { return (I18N[LANG] || I18N.ar)[key] || I18N.ar[key] || key; }

function applyLang() {
  const ar = LANG === "ar";
  document.documentElement.lang = LANG;
  document.documentElement.dir = ar ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  const inp = document.getElementById("input");
  if (inp) inp.placeholder = t("placeholder");
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  localStorage.setItem("nexus_zui_lang", LANG);
}

/* ══ HTTP helpers — التوكن يُرفَق مع كل طلب إن كان مخزناً ══ */
function authHeaders(extra) {
  const h = Object.assign({}, extra || {});
  const tok = localStorage.getItem("nexus_auth_token") || "";
  if (tok) h["X-Auth-Token"] = tok;
  return h;
}

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ headers: authHeaders() }, opts || {}));
  if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
  return res.json();
}

function toast(msg, isErr) {
  const box = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = "toast" + (isErr ? " err" : "");
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), 3800);
}

/* ══ Markdown آمن: تهريب أولًا ثم ترميز محدود + كود مُظلل ══ */
function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMd(text) {
  const parts = [];
  const src = String(text || "");
  const re = /```([\w+-]*)\n([\s\S]*?)```/g;
  let last = 0, m;
  while ((m = re.exec(src)) !== null) {
    if (m.index > last) parts.push({ t: "md", v: src.slice(last, m.index) });
    parts.push({ t: "code", lang: m[1] || "", v: m[2] });
    last = re.lastIndex;
  }
  if (last < src.length) parts.push({ t: "md", v: src.slice(last) });
  return parts;
}

function mdInline(s) {
  return s
    .replace(/`([^`]+)`/g, (_, c) => `<code>${c}</code>`)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function mdBlock(s) {
  const lines = esc(s).split("\n");
  let out = "", inList = false;
  for (const line of lines) {
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    const hd = line.match(/^(#{1,3})\s+(.*)$/);
    if (li || ol) {
      if (!inList) { out += "<ul>"; inList = true; }
      out += `<li>${mdInline((li || ol)[1])}</li>`;
      continue;
    }
    if (inList) { out += "</ul>"; inList = false; }
    if (hd) { out += `<h${hd[1].length}>${mdInline(hd[2])}</h${hd[1].length}>`; continue; }
    if (line.trim() === "") { out += "</p><p>"; continue; }
    out += mdInline(line) + "\n";
  }
  if (inList) out += "</ul>";
  return `<p>${out}</p>`;
}

let codesToHighlight = [];
function renderBubble(content) {
  const parts = renderMd(content);
  let html = "";
  codesToHighlight = [];
  for (const p of parts) {
    if (p.t === "md") { html += mdBlock(p.v); continue; }
    const id = "code-" + Math.random().toString(36).slice(2, 9);
    codesToHighlight.push({ id, lang: p.lang, raw: p.v });
    html += `<div class="codeblock"><div class="code-head"><span>${esc(p.lang || "code")}</span>` +
      `<button class="copy" data-target="${id}">${t("copy")}</button></div>` +
      `<pre><code id="${id}" class="hljs${p.lang ? " language-" + esc(p.lang) : ""}">${esc(p.v)}</code></pre></div>`;
  }
  return html;
}

function highlightAndWire(bubble) {
  if (window.hljs) {
    bubble.querySelectorAll("pre code").forEach(el => { try { window.hljs.highlightElement(el); } catch (e) { /* best-effort */ } });
  }
  bubble.querySelectorAll(".copy").forEach(btn => {
    btn.addEventListener("click", () => {
      const code = document.getElementById(btn.dataset.target);
      if (code) navigator.clipboard.writeText(code.textContent)
        .then(() => { btn.textContent = t("copied"); setTimeout(() => { btn.textContent = t("copy"); }, 1200); })
        .catch(() => {});
    });
  });
}

/* ══ الحوار ══ */
const state = { conversations: [], currentId: null, agent: localStorage.getItem("nexus_zui_agent") || "", busy: false };

function el(id) { return document.getElementById(id); }

function scrollDown(force) {
  const chat = el("chat");
  if (force || chat.scrollHeight - chat.scrollTop - chat.clientHeight < 160) {
    chat.scrollTop = chat.scrollHeight;
  }
}

function hideWelcome() { const w = el("welcome"); if (w) w.style.display = "none"; }

function addUserMsg(text) {
  hideWelcome();
  const wrap = document.createElement("div");
  wrap.className = "msg msg-user";
  wrap.innerHTML = `<div class="msg-meta"><span class="badge">${t("you")}</span></div>` +
    `<div class="bubble"><p>${mdInline(esc(text)).replace(/\n/g, "<br>")}</p></div>`;
  el("messages").appendChild(wrap);
  scrollDown(true);
}

function addAgentShell(agentName) {
  hideWelcome();
  const wrap = document.createElement("div");
  wrap.className = "msg msg-agent";
  wrap.innerHTML = `<div class="msg-meta"><span class="badge">◈ ${esc(agentName || "default")}</span>` +
    `<span class="pill badge-tier" data-role="tier"></span></div>` +
    `<div class="bubble"><span class="caret"></span></div>`;
  el("messages").appendChild(wrap);
  scrollDown(true);
  return wrap;
}

function finalizeAgent(wrap, meta) {
  const bubble = wrap.querySelector(".bubble");
  const caret = bubble.querySelector(".caret");
  if (caret) caret.remove();
  const full = wrap.dataset.full || "";
  bubble.innerHTML = renderBubble(full);
  highlightAndWire(bubble);
  const tier = wrap.querySelector('[data-role="tier"]');
  if (tier && meta && meta.tier) tier.textContent = meta.tier;
  if (meta && meta.reflection && meta.reflection.rating) {
    const note = document.createElement("div");
    note.className = "reflection";
    note.textContent = `تقييم ذاتي: ${meta.reflection.rating}${meta.reflection.reason ? " — " + meta.reflection.reason : ""}${meta.retried ? " (بعد إعادة محاولة)" : ""}`;
    wrap.appendChild(note);
  }
  scrollDown(true);
}

async function sendMessage() {
  if (state.busy) return;
  const input = el("input");
  const message = input.value.trim();
  if (!message) { toast(t("emptyMsg"), true); return; }
  input.value = ""; input.style.height = "auto";
  addUserMsg(message);
  state.busy = true;
  el("sendBtn").disabled = true;
  const wrap = addAgentShell(state.agent);
  const bubble = wrap.querySelector(".bubble");
  let full = "";
  const meta = { tier: "", reflection: null, retried: false };
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json", Accept: "text/event-stream" }),
      body: JSON.stringify({ message, agent: state.agent || null, conversation_id: state.currentId }),
    });
    if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    let done = false;
    while (!done) {
      const { value, done: rdDone } = await reader.read();
      if (rdDone) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const raw = buf.slice(0, idx).trim();
        buf = buf.slice(idx + 2);
        if (!raw.startsWith("data:")) continue;
        const payload = raw.slice(5).trim();
        if (payload === "[DONE]") { done = true; break; }
        let ev;
        try { ev = JSON.parse(payload); } catch (e) { continue; }
        if (ev.type === "plan") {
          const badge = wrap.querySelector(".badge");
          if (badge && ev.agent) badge.textContent = "◈ " + ev.agent;
          if (ev.conversation_id && !state.currentId) {
            state.currentId = ev.conversation_id;
            loadConversations();
          }
        } else if (ev.type === "chunk") {
          full += ev.content || "";
          wrap.dataset.full = full;
          bubble.innerHTML = renderBubble(full) + '<span class="caret"></span>';
          scrollDown(false);
          if (ev.provider && !meta.tier) {
            meta.tier = ev.provider;
            const tierEl = wrap.querySelector('[data-role="tier"]');
            if (tierEl) tierEl.textContent = ev.provider;
          }
          if (ev.reflection) meta.reflection = ev.reflection;
          if (ev.retried) meta.retried = true;
        } else if (ev.type === "error") {
          wrap.classList.add("msg-error");
          full += (full ? "\n\n" : "") + "⚠ " + (ev.content || "error");
          wrap.dataset.full = full;
        }
      }
    }
  } catch (e) {
    wrap.classList.add("msg-error");
    full += (full ? "\n\n" : "") + `⚠ ${t("loadFail")}: ${e.message}`;
    wrap.dataset.full = full;
  }
  finalizeAgent(wrap, meta);
  state.busy = false;
  el("sendBtn").disabled = false;
  el("input").focus();
}

/* ══ المحادثات ══ */
async function loadConversations() {
  try {
    const data = await api("/api/conversations?limit=60");
    state.conversations = data.conversations || [];
    const list = el("convList");
    list.innerHTML = "";
    for (const conv of state.conversations) {
      const item = document.createElement("div");
      const id = conv.id || conv.thread_id || conv.conversation_id || "";
      item.className = "conv" + (id === state.currentId ? " active" : "");
      item.innerHTML = `<span class="dot">•</span> ${esc(conv.title || t("newConv"))}`;
      item.addEventListener("click", () => openConversation(id, conv.title));
      list.appendChild(item);
    }
  } catch (e) { /* القائمة تحسين لا أساس */ }
}

function openConversation(id, title) {
  state.currentId = id;
  hideWelcome();
  el("messages").innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "msg msg-user";
  wrap.innerHTML = `<div class="msg-meta"><span class="badge">${t("you")}</span></div>` +
    `<div class="bubble"><p>${esc(title || "")}</p></div>`;
  el("messages").appendChild(wrap);
  loadConversations();
}

async function newChat() {
  state.currentId = null;
  el("messages").innerHTML = "";
  el("welcome").style.display = "";
  loadConversations();
}

/* ══ الشريط العلوي والحالة ══ */
async function loadAgents() {
  const sel = el("agentSelect");
  sel.innerHTML = "";
  const def = document.createElement("option");
  def.value = ""; def.textContent = LANG === "ar" ? "تلقائي (توجيه عرقي)" : "auto (raced routing)";
  sel.appendChild(def);
  try {
    const data = await api("/api/agents");
    for (const a of data.agents || []) {
      const opt = document.createElement("option");
      opt.value = a.id;
      opt.textContent = `${a.id}${a.group ? " — " + a.group : ""}`;
      sel.appendChild(opt);
    }
  } catch (e) { /* القائمة تحسين */ }
  sel.value = state.agent;
}

async function loadStatus() {
  const pill = el("connPill");
  try {
    const data = await api("/api/status");
    const providers = [];
    if (data.providers) {
      for (const p of Object.values(data.providers)) {
        if (p && (p.available || p.configured)) providers.push(p.name || "?");
      }
    }
    pill.textContent = `${t("online")}${providers.length ? " · " + providers.slice(0, 3).join(" · ") : ""}`;
    pill.className = "pill pill-ok";
    const pills = el("statusPills");
    pills.innerHTML = "";
    for (const k of ["version", "mode", "agents"]) {
      if (data[k] !== undefined && data[k] !== null) {
        const s = document.createElement("span");
        s.className = "pill";
        s.textContent = `${k}: ${String(data[k]).slice(0, 24)}`;
        pills.appendChild(s);
      }
    }
  } catch (e) {
    pill.textContent = t("offline");
    pill.className = "pill pill-bad";
  }
}

/* ══ لوحة الأدوات — التبويبات الأربع ══ */
const PANEL = { tab: "agents" };

function panelBody() { return el("panelBody"); }

function renderAgents(data) {
  const cards = [];
  cards.push(`<div class="card"><h4>${t("agents")}</h4>`);
  for (const a of data.agents || []) {
    cards.push(`<div><span class="v">${esc(a.id)}</span> <span class="k">${esc(a.group || "")}</span></div>`);
  }
  cards.push("</div>");
  return cards.join("");
}

function renderMonitor(data) {
  const evals = data.evaluations || {};
  const keys = Object.keys(evals);
  if (!keys.length) return `<div class="loading">${t("noMonitor")}</div>`;
  const s = data.summary || {};
  const head = `<div class="card"><h4>${t("fleetEval")}</h4>` +
    `<div><span class="k">monitor-clear: </span><span class="v tier-S">${s["monitor-clear"] || 0}</span>` +
    ` · <span class="k">watch: </span><span class="v tier-B">${s["watch"] || 0}</span>` +
    ` · <span class="k">council-review: </span><span class="v">${s["council-review"] || 0}</span>` +
    ` · <span class="k">insufficient: </span><span class="k">${s["insufficient-data"] || 0}</span></div></div>`;
  const rows = keys.map(name => {
    const st = evals[name];
    return `<div class="card"><h4>${esc(name)} <span class="grade-pill grade-${esc(st.grade)}">${esc(st.grade)}</span></h4>` +
      `<div><span class="k">runs: </span><span class="v">${st.runs}</span>` +
      ` · <span class="k">ok: </span><span class="v">${st.ok}</span>` +
      ` · <span class="k">fail: </span><span class="v">${st.fail}</span>` +
      ` · <span class="k">avg_ms: </span><span class="v">${st.avg_ms}</span></div>` +
      `<div style="margin-top:6px"><span class="v">${esc((st.verdict || {}).action || "")}</span>` +
      ` <span class="k">— ${esc((st.verdict || {}).reason || "")}</span></div></div>`;
  });
  return head + rows.join("");
}

async function loadPanel() {
  const body = panelBody();
  if (PANEL.tab === "agents") {
    body.innerHTML = `<div class="loading">…</div>`;
    try { body.innerHTML = renderAgents(await api("/api/agents")); }
    catch (e) { body.innerHTML = `<div class="loading">${t("loadFail")}: ${esc(e.message)}</div>`; }
  } else if (PANEL.tab === "monitor") {
    body.innerHTML = `<div class="loading">…</div>`;
    try { body.innerHTML = renderMonitor(await api("/api/monitor")); }
    catch (e) { body.innerHTML = `<div class="loading">${t("loadFail")}: ${esc(e.message)}</div>`; }
  } else if (PANEL.tab === "traces") {
    body.innerHTML = `<div class="loading">…</div>`;
    try {
      const data = await api("/api/traces?limit=40");
      const rows = data.traces || data.events || [];
      if (!rows.length) { body.innerHTML = `<div class="loading">${t("noTraces")}</div>`; return; }
      body.innerHTML = rows.map(ev =>
        `<div class="trace-item">${esc(String(ev.ts || "").slice(11, 19))} · ${esc(ev.agent || "?")} · ${esc(ev.tool || "?")} · ${esc(ev.outcome || "?")} · ${esc(String(ev.duration_ms || 0))}ms</div>`
      ).join("");
    } catch (e) { body.innerHTML = `<div class="loading">${t("loadFail")}: ${esc(e.message)}</div>`; }
  } else if (PANEL.tab === "council") {
    body.innerHTML =
      `<div class="card"><h4>${t("tabCouncil")}</h4>` +
      `<textarea id="councilTopic" rows="2" placeholder="${t("councilPlaceholder")}" style="width:100%;background:var(--surface2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px;font-family:inherit"></textarea>` +
      `<button id="councilAskBtn" class="btn-primary" style="margin-top:8px">${t("councilAsk")}</button></div>` +
      `<div id="councilOut"></div>`;
    el("councilAskBtn").addEventListener("click", askCouncil);
  }
}

async function askCouncil() {
  const topic = el("councilTopic").value.trim();
  const out = el("councilOut");
  if (!topic) return;
  out.innerHTML = `<div class="loading">…</div>`;
  try {
    const data = await api("/api/council/debate", {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ topic, rounds: 1 }),
    });
    if (!data.ok) throw new Error(data.error || "council unavailable");
    const result = data.result || {};
    const msgs = Array.isArray(result) ? result : (result.messages || result.rounds || []);
    let html = "";
    const items = Array.isArray(msgs) ? msgs : [msgs];
    for (const m of items.slice(0, 12)) {
      const who = esc(m.member || m.name || m.role || "—");
      const what = esc(String(m.opinion || m.text || m.verdict || JSON.stringify(m)).slice(0, 400));
      html += `<div class="council-msg"><strong>${who}</strong><br>${what}</div>`;
    }
    out.innerHTML = html || `<div class="loading">${esc(JSON.stringify(result).slice(0, 600))}</div>`;
  } catch (e) {
    out.innerHTML = `<div class="loading">${t("loadFail")}: ${esc(e.message)}</div>`;
  }
}

/* ══ التركيب ══ */
function wire() {
  el("sendBtn").addEventListener("click", sendMessage);
  el("input").addEventListener("keydown", ev => {
    if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendMessage(); }
  });
  el("input").addEventListener("input", function () {
    this.style.height = "auto";
    this.style.height = Math.min(this.scrollHeight, 180) + "px";
  });
  el("newChatBtn").addEventListener("click", newChat);
  el("agentSelect").addEventListener("change", function () {
    state.agent = this.value;
    localStorage.setItem("nexus_zui_agent", state.agent);
  });
  el("langToggle").addEventListener("click", () => {
    LANG = LANG === "ar" ? "en" : "ar";
    applyLang(); loadAgents(); loadPanel();
  });
  el("panelToggle").addEventListener("click", () => {
    el("app").classList.toggle("panel-open");
    loadPanel();
  });
  el("panelClose").addEventListener("click", () => el("app").classList.remove("panel-open"));
  el("burger").addEventListener("click", () => el("app").classList.toggle("sidebar-open"));
  document.querySelectorAll(".tab").forEach(tabBtn => {
    tabBtn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
      tabBtn.classList.add("active");
      PANEL.tab = tabBtn.dataset.tab;
      loadPanel();
    });
  });
  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      el("input").value = chip.dataset.chip;
      el("input").focus();
    });
  });
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/zui/sw.js", { scope: "/zui/" }).catch(() => { /* best-effort */ });
  }
}

function boot() {
  applyLang();
  wire();
  loadAgents();
  loadStatus();
  loadConversations();
  setInterval(loadStatus, 30000);
}

document.addEventListener("DOMContentLoaded", boot);

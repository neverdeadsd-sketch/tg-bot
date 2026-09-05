/* tgnames — front end. No framework, no build step: the server that hosts this
   runs on the standard library alone, and the page should not need more. */

const TOKEN = new URLSearchParams(location.search).get("t") || "";

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// Status colours are fixed roles, never themed, and always ship with a label —
// hue alone never carries the meaning.
const STATUS = {
  new:         { label: "Не проверено",        color: "var(--st-unknown)" },
  available:   { label: "Свободно",            color: "var(--st-good)" },
  unclaimed:   { label: "Владельца не видно",  color: "var(--st-unknown)" },
  purchasable: { label: "Продаётся",           color: "var(--st-warning)" },
  taken:       { label: "Занято",              color: "var(--st-critical)" },
  invalid:     { label: "Недопустимо",         color: "var(--st-warning)" },
  claimed:     { label: "Занято мной",         color: "var(--st-good)" },
  failed:      { label: "Ошибка",              color: "var(--st-critical)" },
  skipped:     { label: "Пропущено",           color: "var(--st-unknown)" },
};

const CHART_SERIES = [
  { key: "free",     label: "Свободно (API)",   color: "var(--st-good)" },
  { key: "unknown",  label: "Владельца не видно", color: "var(--st-unknown)" },
  { key: "reserved", label: "Зарезервировано",  color: "var(--st-warning)" },
  { key: "taken",    label: "Занято",           color: "var(--st-critical)" },
];

const COMPONENT_LABELS = {
  length: "Длина", charset: "Алфавит", lexical: "Смысл",
  pattern: "Структура", phonetic: "Звучание",
};


/* The engine speaks English — that is the right language for code and for the
   test suite. The interface speaks Russian, so its strings are translated here,
   at the edge, by pattern. Anything unrecognised passes through unchanged. */
const PHRASES = [
  [/^length (\d+)$/,                         (m) => `длина ${m[1]}`],
  [/^letters only$/,                          () => "только буквы"],
  [/^contains (\d+) digit\(s\)$/,            (m) => `цифр: ${m[1]}`],
  [/^contains (\d+) underscore\(s\)$/,       (m) => `подчёркиваний: ${m[1]}`],
  [/^exact dictionary word \((.+)\)$/,        (m) => `точное словарное слово (${m[1]})`],
  [/^compound of (.+)$/,                      (m) => `составное: ${m[1]}`],
  [/^word '(.+)' with decoration$/,           (m) => `слово «${m[1]}» с добавками`],
  [/^contains '(.+)'$/,                       (m) => `содержит «${m[1]}»`],
  [/^single repeated character$/,             () => "один повторяющийся символ"],
  [/^repeats the block '(.+)'$/,              (m) => `повтор блока «${m[1]}»`],
  [/^alphabetic\/numeric run$/,               () => "последовательный ряд"],
  [/^keyboard row run$/,                      () => "ряд клавиатуры"],
  [/^palindrome$/,                            () => "палиндром"],
  [/^repdigit tail '(.+)'$/,                  (m) => `хвост из одинаковых цифр «${m[1]}»`],
  [/^year tail '(.+)'$/,                      (m) => `год в конце «${m[1]}»`],
  [/^triple letter$/,                         () => "тройная буква"],
  [/^(\d+) consonants in a row$/,             (m) => `${m[1]} согласных подряд`],
  [/^easy to pronounce$/,                     () => "легко произносится"],
  [/^no letters$/,                            () => "нет букв"],
  [/^no meaning, no structure, hard to pronounce$/,
                                              () => "ни смысла, ни структуры, трудно произнести"],
  [/^reserved\/trademark word.*$/,            () => "зарезервированное слово или торговая марка — регистрацию, скорее всего, отзовут"],
  [/^contains a reserved\/trademark word$/,   () => "содержит зарезервированное слово"],
  [/^contains blocked substring '(.+)'$/,     (m) => `содержит запрещённую подстроку «${m[1]}»`],
  [/^'bot' suffix is read as a bot account$/, () => "суффикс bot читается как бот-аккаунт"],
  [/^short dictionary word.*$/,               () => "короткое словарное слово — Telegram обычно придерживает такие для аукциона Fragment, поэтому проверка по странице вводит в заблуждение"],
  // notes written by the scanners
  [/^via t\.me page: owner visible$/,         () => "страница t.me: владелец есть"],
  [/^via t\.me page: no owner visible$/,      () => "страница t.me: владельца не видно"],
  [/^via t\.me page: listed for sale on Fragment$/,
                                              () => "страница t.me: выставлено на Fragment"],
  [/^404 from t\.me.*$/,                      () => "t.me ответил 404"],
  [/^marked (by hand|in the app)$/,           () => "отмечено вручную"],
  [/^occupied$/,                              () => "занято"],
  [/^free$/,                                  () => "свободно"],
  [/^sold via Fragment auction$/,             () => "продаётся через Fragment"],
  [/^rejected by Telegram$/,                  () => "отклонено Telegram"],
  [/^taken between check and claim$/,         () => "занято между проверкой и захватом"],
];

function ru(text) {
  if (!text) return "";
  for (const [pattern, render] of PHRASES) {
    const m = pattern.exec(text);
    if (m) return render(m);
  }
  return text;
}

// Short on purpose: these are chips in a dense table, and the full value
// stays in the tooltip.
const TAG_LABELS = {
  "likely-reserved": "резерв?",
  "reserved": "резерв",
  "reserved-part": "часть-резерв",
  "risky": "риск",
  "noise": "шум",
  "bot-like": "бот?",
  "prime": "топ",
  "repeat": "повтор",
  "run": "ряд",
  "palindrome": "палиндром",
  "keyboard": "клавиши",
  "repdigit": "цифры",
  "year": "год",
  "letter-number": "буква+№",
};

const state = { stats: null, items: [], busy: false, pollTimer: null };

/* ── transport ─────────────────────────────────────────────────────────── */
async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "X-Token": TOKEN, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const data = await res.json().catch(() => ({ error: "bad response" }));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

function toast(message, ms = 2600) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, ms);
}

const escapeHtml = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ── navigation ────────────────────────────────────────────────────────── */
const VIEWS = ["overview", "candidates", "analyze", "hunt"];

function showView(view, { focus = false } = {}) {
  if (!VIEWS.includes(view)) view = "overview";
  $$(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === view));
  $$(".view").forEach((v) => v.classList.toggle("is-active", v.dataset.view === view));
  if (view === "candidates") loadCandidates();
  if (view === "analyze") {
    const input = $("#analyzeInput");
    if (!input.value) {
      input.value = "goldvault";     // so the breakdown is visible immediately
      input.dispatchEvent(new Event("input"));
    }
    if (focus) { input.focus(); input.select(); }
  }
}

$$(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    // The hash keeps the current view across a reload and makes each one
    // linkable; the hashchange handler does the actual switching.
    location.hash = btn.dataset.view;
  });
});
window.addEventListener("hashchange", () =>
  showView(location.hash.slice(1), { focus: true }));

/* ── overview ──────────────────────────────────────────────────────────── */
function renderTiles(stats) {
  const c = stats.counts || {};
  const tiles = [
    { label: "Всего", value: stats.total, hint: "кандидатов в базе", color: null },
    { label: "Свободно", value: c.available || 0, hint: "подтверждено через API", color: "var(--st-good)" },
    { label: "Владельца не видно", value: c.unclaimed || 0, hint: "занимаемость не проверена", color: "var(--st-unknown)" },
    { label: "Продаётся", value: c.purchasable || 0, hint: "аукцион Fragment", color: "var(--st-warning)" },
    { label: "Занято", value: c.taken || 0, hint: "владелец найден", color: "var(--st-critical)" },
    { label: "Занято мной", value: c.claimed || 0, hint: "в вашем распоряжении", color: "var(--st-good)" },
  ];
  $("#tiles").innerHTML = tiles.map((t) => `
    <div class="tile">
      <div class="tile-label">
        ${t.color ? `<span class="dot" style="background:${t.color}"></span>` : ""}
        ${escapeHtml(t.label)}
      </div>
      <div class="tile-value">${t.value.toLocaleString("ru")}</div>
      <div class="tile-hint">${escapeHtml(t.hint)}</div>
    </div>`).join("");
}

function renderChart(byLength) {
  const legend = CHART_SERIES.map((s) => `
    <span class="legend-item">
      <span class="dot" style="background:${s.color}"></span>${escapeHtml(s.label)}
    </span>`).join("");
  $("#chartLegend").innerHTML = legend;

  if (!byLength.length) {
    $("#lengthChart").innerHTML =
      `<p class="chart-empty">Пока нечего показать — запустите проверку на вкладке «Поиск».</p>`;
    $("#chartNote").textContent = "";
    return;
  }

  const max = Math.max(...byLength.map((r) => CHART_SERIES.reduce((a, s) => a + (r[s.key] || 0), 0)));
  $("#lengthChart").innerHTML = byLength.map((row) => {
    const total = CHART_SERIES.reduce((a, s) => a + (row[s.key] || 0), 0);
    const segs = CHART_SERIES.filter((s) => row[s.key] > 0).map((s) => {
      const n = row[s.key];
      const pct = (n / total) * 100;
      // A number is drawn inside a segment only when it comfortably fits.
      const label = pct > 13 ? `<span>${n}</span>` : "";
      return `<div class="chart-seg" style="flex:${n};background:${s.color}"
                   title="${escapeHtml(s.label)}: ${n} из ${total}">${label}</div>`;
    }).join("");
    return `
      <div class="chart-row">
        <div class="chart-label">${row.length} симв.</div>
        <div class="chart-track" style="width:${Math.max(8, (total / max) * 100)}%">${segs}</div>
        <div class="chart-total">${total}</div>
      </div>`;
  }).join("");

  const dead = byLength.filter((r) => !r.free && !r.unknown).map((r) => r.length);
  $("#chartNote").textContent = dead.length
    ? `Полосы ${dead.join(", ")} симв. выбраны полностью — проверять их снова значит тратить запросы. `
      + `«Свободно» подтверждается только через API; «владельца не видно» этого не гарантирует.`
    : `«Свободно» подтверждается только через API. «Владельца не видно» означает лишь, `
      + `что страница не отдана — выставленные на продажу имена умеют то же самое.`;
}

function renderQuota(q) {
  $("#quota").innerHTML = `
    <div class="quota-row"><span>Проверок за час</span><b>${q.check.hour}/${q.check.hourMax}</b></div>
    <div class="quota-row"><span>Захватов за сутки</span><b>${q.claim.day}/${q.claim.dayMax}</b></div>`;
}

function renderEvents(events) {
  $("#events").innerHTML = events.length
    ? events.map((e) => `
        <li>
          <span class="ev-kind">${escapeHtml(e.kind)}</span>
          <span class="ev-name">${e.username ? "@" + escapeHtml(e.username) : ""}</span>
          <span class="ev-detail">${escapeHtml(ru(e.detail || ""))}</span>
        </li>`).join("")
    : `<li><span class="ev-detail">Событий пока нет</span></li>`;
}

async function loadStats() {
  const stats = await api(`/api/stats`);
  state.stats = stats;
  renderTiles(stats);
  renderChart(stats.byLength);
  renderQuota(stats.quota);
  renderEvents(stats.events);
  $("#dbPath").textContent = stats.db;
  $("#dbPath").title = stats.db;
  $("[data-count=candidates]").textContent = stats.total ? stats.total.toLocaleString("ru") : "";

  const sel = $("#strategy");
  if (!sel.options.length) {
    sel.innerHTML = stats.strategies.map((s) =>
      `<option value="${s}"${s === "compounds" ? " selected" : ""}>${s}</option>`).join("");
  }
}

/* ── candidates ────────────────────────────────────────────────────────── */
function statusPill(status) {
  const s = STATUS[status] || { label: status, color: "var(--st-unknown)" };
  return `<span class="pill"><span class="dot" style="background:${s.color}"></span>${escapeHtml(s.label)}</span>`;
}

function tagChip(tag) {
  const cls = tag === "likely-reserved" ? "tag tag-warn"
            : (tag === "risky" || tag === "reserved") ? "tag tag-risk" : "tag";
  const label = TAG_LABELS[tag] || tag;
  return `<span class="${cls}" title="${escapeHtml(tag)}">${escapeHtml(label)}</span>`;
}

function tagList(tags) {
  // Warning tags first — they are the ones that change a decision — then at
  // most two chips so a row stays one line tall.
  const ordered = [...tags].sort((a, b) =>
    (b === "likely-reserved" || b === "risky" || b === "reserved") -
    (a === "likely-reserved" || a === "risky" || a === "reserved"));
  const shown = ordered.slice(0, 2).map(tagChip).join("");
  const rest = ordered.length - 2;
  return shown + (rest > 0
    ? `<span class="tag-more" title="${escapeHtml(ordered.slice(2).join(", "))}">+${rest}</span>`
    : "");
}

async function loadCandidates() {
  const params = new URLSearchParams({
    status: $("#statusFilter").value,
    q: $("#search").value,
    sort: $("#sortBy").value,
    limit: "400",
  });
  const data = await api(`/api/candidates?${params}`);
  let items = data.items;
  if ($("#hideReserved").checked) {
    items = items.filter((i) => !i.tags.includes("likely-reserved"));
  }
  state.items = items;

  $("#candSub").textContent =
    `${data.matched.toLocaleString("ru")} совпадений, показано ${items.length}`;
  $("#candEmpty").hidden = items.length > 0;
  $("#candBody").innerHTML = items.map((i) => `
    <tr data-name="${escapeHtml(i.username)}">
      <td>
        <div class="handle">@${escapeHtml(i.username)}<span class="handle-len">${i.length}</span></div>
      </td>
      <td>
        <div class="score-cell">
          <span class="score-num">${i.score.toFixed(1)}</span>
          <span class="score-bar"><span style="width:${i.score}%"></span></span>
        </div>
      </td>
      <td><span class="tier tier-${escapeHtml(i.tier)}">${escapeHtml(i.tier)}</span></td>
      <td>${statusPill(i.status)}</td>
      <td><div class="tags">${tagList(i.tags)}</div></td>
      <td><div class="cell-note" title="${escapeHtml(ru(i.note))}">${escapeHtml(ru(i.note))}</div></td>
      <td>
        <div class="row-actions">
          <button class="btn btn-mini" data-act="open" title="Открыть t.me">t.me</button>
          <button class="btn btn-mini" data-act="claimed" title="Отметить как занятое мной">Занял</button>
          <button class="btn btn-mini" data-act="skipped" title="Скрыть из очереди">Скрыть</button>
        </div>
      </td>
    </tr>`).join("");
}

$("#candBody").addEventListener("click", async (event) => {
  const btn = event.target.closest("button[data-act]");
  if (!btn) return;
  const name = btn.closest("tr").dataset.name;
  const act = btn.dataset.act;
  if (act === "open") { window.open(`https://t.me/${name}`, "_blank", "noopener"); return; }
  await post("/api/mark", { usernames: [name], status: act });
  toast(act === "claimed" ? `@${name} отмечен как занятый вами` : `@${name} скрыт`);
  await Promise.all([loadCandidates(), loadStats()]);
});

let searchTimer;
$("#search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadCandidates, 180);
});
["#statusFilter", "#sortBy", "#hideReserved"].forEach((sel) =>
  $(sel).addEventListener("change", loadCandidates));

$("#copyBtn").addEventListener("click", async () => {
  const text = state.items.map((i) => i.username).join("\n");
  try {
    await navigator.clipboard.writeText(text);
    toast(`Скопировано имён: ${state.items.length}`);
  } catch {
    toast("Браузер не дал доступ к буферу обмена");
  }
});

/* ── analyze ───────────────────────────────────────────────────────────── */
function renderAnalysis(result) {
  if (!result) {
    $("#analyzeResult").innerHTML = "";
    $("#analyzeReasons").innerHTML = "";
    return;
  }
  if (!result.valid) {
    $("#analyzeResult").innerHTML =
      `<p class="invalid">Недопустимый юзернейм: ${escapeHtml(result.error)}</p>`;
    $("#analyzeReasons").innerHTML = "";
    return;
  }
  const comps = Object.entries(result.components).map(([key, value]) => `
    <div class="comp-row">
      <span class="comp-name">${escapeHtml(COMPONENT_LABELS[key] || key)}</span>
      <span class="comp-track"><span class="comp-fill" style="width:${value}%"></span></span>
      <span class="comp-val">${Math.round(value)}</span>
    </div>`).join("");

  $("#analyzeResult").innerHTML = `
    <div class="verdict">
      <span class="verdict-score">${result.score.toFixed(1)}</span>
      <div class="verdict-meta">
        <div><span class="tier tier-${escapeHtml(result.tier)}">${escapeHtml(result.tier)}</span>
          <span class="verdict-band" style="margin-left:8px">тир ${escapeHtml(result.tier)} · ориентир $${escapeHtml(result.value_hint)}</span>
        </div>
        <div class="tags">${result.tags.map(tagChip).join("")}</div>
      </div>
    </div>
    <div class="components">${comps}</div>`;

  $("#analyzeReasons").innerHTML =
    result.reasons.map((r) => `<div class="reason">${escapeHtml(ru(r))}</div>`).join("");
}

let analyzeTimer;
$("#analyzeInput").addEventListener("input", (event) => {
  clearTimeout(analyzeTimer);
  const value = event.target.value;
  analyzeTimer = setTimeout(async () => {
    if (!value.trim()) return renderAnalysis(null);
    const data = await api(`/api/analyze?u=${encodeURIComponent(value)}`);
    renderAnalysis(data.result);
  }, 140);
});

/* ── jobs ──────────────────────────────────────────────────────────────── */
function renderLogLine(line) {
  if (line.level === "row") {
    const [name, score, tier, verdict, title] = line.text.split("|");
    const s = STATUS[verdict === "reserved" ? "purchasable" : verdict]
              || { label: verdict, color: "var(--st-unknown)" };
    const label = verdict === "reserved" ? "Зарезервировано?" : s.label;
    return `<div class="log-line log-row">
      <span class="pill"><span class="dot" style="background:${s.color}"></span>${escapeHtml(label)}</span>
      <span><span class="handle">@${escapeHtml(name)}</span>
        <span class="log-title"> ${escapeHtml(score)} ${escapeHtml(tier)} ${escapeHtml(title || "")}</span>
      </span>
    </div>`;
  }
  return `<div class="log-line log-${escapeHtml(line.level)}">${escapeHtml(line.text)}</div>`;
}

function renderJob(job, busy) {
  state.busy = busy;
  $("[data-busy]").hidden = !busy;
  $("#stopBtn").hidden = !busy;
  ["#generateBtn", "#scanBtn", "#rescoreBtn"].forEach((sel) => { $(sel).disabled = busy; });

  if (!job) return;
  const log = $("#log");
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.innerHTML = job.lines.length
    ? job.lines.map(renderLogLine).join("")
    : `<p class="log-empty">${escapeHtml(job.message || "Запускается…")}</p>`;
  if (atBottom) log.scrollTop = log.scrollHeight;

  const pct = job.total ? Math.min(100, (job.done / job.total) * 100) : 0;
  $("#progressWrap").hidden = !job.total || job.state !== "running";
  $("#progressFill").style.width = `${pct}%`;

  const states = { running: "выполняется", finished: "готово",
                   failed: "ошибка", stopped: "остановлено" };
  const counter = job.total ? ` · ${job.done}/${job.total}` : "";
  $("#jobMeta").textContent =
    `${job.kind} — ${states[job.state] || job.state}${counter} · ${job.elapsed}с`;
}

async function pollJob() {
  try {
    const { job, busy } = await api("/api/job");
    renderJob(job, busy);
    if (!busy && state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      await Promise.all([loadStats(), loadCandidates()]);
    }
  } catch (err) { /* the server may be restarting; the next tick retries */ }
}

function startPolling() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(pollJob, 700);
  pollJob();
}

async function launch(path, body, label) {
  try {
    await post(path, body);
    toast(`${label} запущено`);
    startPolling();
  } catch (err) {
    toast(err.message);
  }
}

$("#generateBtn").addEventListener("click", () => launch("/api/generate", {
  strategy: $("#strategy").value,
  limit: Number($("#genLimit").value),
  minLength: Number($("#minLength").value),
  noFilter: $("#noFilter").checked,
}, "Генерация"));

$("#scanBtn").addEventListener("click", () => launch("/api/scan", {
  limit: Number($("#scanLimit").value),
  delay: Number($("#scanDelay").value),
  includeReserved: $("#includeReserved").checked,
  fragmentControls: [$("#fragmentControl").value.trim().replace(/^@/, "")].filter(Boolean),
}, "Проверка"));

$("#rescoreBtn").addEventListener("click", () => launch("/api/rescore", {}, "Пересчёт"));

$("#stopBtn").addEventListener("click", async () => {
  await post("/api/job/stop");
  toast("Останавливаю после текущего запроса…");
});

$("#refreshBtn").addEventListener("click", async () => {
  await loadStats();
  toast("Обновлено");
});

/* ── boot ──────────────────────────────────────────────────────────────── */
(async function boot() {
  if (!TOKEN) {
    document.body.innerHTML =
      `<div class="empty">Откройте приложение по ссылке из терминала — в ней есть ключ доступа.</div>`;
    return;
  }
  try {
    await loadStats();
    showView(location.hash.slice(1));
    await pollJob();
    if (state.busy) startPolling();
  } catch (err) {
    toast(`Не удалось связаться с сервером: ${err.message}`, 6000);
  }
})();

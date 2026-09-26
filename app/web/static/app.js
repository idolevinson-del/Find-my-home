const $ = (s, el = document) => el.querySelector(s);

// Two modes: the local server (python run.py → /api/*) or the static site built
// by GitHub Actions (data.json next to this file; statuses kept on this phone).
let STATIC = null;
const LOCAL_KEY = "hunter-status";
const localStatus = () => { try { return JSON.parse(localStorage.getItem(LOCAL_KEY) || "{}"); } catch { return {}; } };
const setLocalStatus = (id, st) => { try { const m = localStatus(); m[id] = st; localStorage.setItem(LOCAL_KEY, JSON.stringify(m)); } catch {} };

const DAY = 24 * 3600 * 1000;
function staticListings(view) {
  const overlay = localStatus();
  const rows = STATIC.listings.map(r => ({ ...r, status: overlay[r.id] || r.status }));
  const keep = { inbox: r => !["SAVED", "REJECTED", "TAKEN"].includes(r.status),
                 saved: r => !["NEW", "REJECTED"].includes(r.status),
                 rejected: r => r.status === "REJECTED", all: () => true }[view];
  const now = Date.now();
  return rows.filter(keep).map(r => ({ ...r, is_new: r.status === "NEW" && now - Date.parse(r.first_seen_at) < DAY }))
    .sort((a, b) => (b.is_new - a.is_new) || ((b.match_score || 0) - (a.match_score || 0)));
}
function staticApi(path, opts) {
  const [p, q] = path.split("?");
  if (p === "/api/listings") return staticListings(new URLSearchParams(q).get("view") || "inbox");
  if (p === "/api/settings") return STATIC.settings;
  if (p === "/api/summary") {
    const inbox = staticListings("inbox");
    return { new: inbox.filter(r => r.is_new).length,
      excellent: inbox.filter(r => (r.match_score || 0) >= 90).length,
      good: inbox.filter(r => (r.match_score || 0) >= 75 && r.match_score < 90).length,
      possible: inbox.filter(r => (r.match_score || 0) < 75).length,
      total: inbox.length, saved: staticListings("saved").length,
      last_scan: STATIC.last_scan, scanning: false, next_scan_at: null, telegram: true };
  }
  const m = p.match(/^\/api\/listings\/(\d+)\/status$/);
  if (m) { setLocalStatus(m[1], JSON.parse(opts.body).status); return { ok: true }; }
  throw new Error("not available on the static site");
}
const api = async (path, opts = {}) => {
  if (STATIC) return staticApi(path, opts);
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
};
const fmt = n => n == null ? "?" : Number(n).toLocaleString("he-IL");
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let view = "inbox";
let settings = null;
let wasScanning = false;

// ---------- views ----------
document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === b));
  view = b.dataset.view;
  $("#list").hidden = view === "settings";
  $("#hero").hidden = view === "settings";
  $("#settings").hidden = view !== "settings";
  view === "settings" ? renderSettings() : loadList();
}));

async function loadList() {
  const rows = await api(`/api/listings?view=${view}`);
  const list = $("#list");
  list.innerHTML = "";
  if (!rows.length) {
    const msg = { inbox: "עדיין אין דירות שמתאימות. הסוכן ממשיך לחפש 🔍", saved: "עוד לא שמרת דירות", rejected: "אין דירות שנדחו" }[view];
    list.innerHTML = `<div class="empty">${msg}</div>`;
    return;
  }
  rows.forEach(r => list.appendChild(card(r)));
}

function card(r) {
  const el = $("#card-tpl").content.firstElementChild.cloneNode(true);
  el.classList.toggle("is-new", !!r.is_new);
  const img = $(".gallery img", el);
  let i = 0;
  if (r.images.length) {
    img.addEventListener("error", () => { img.style.visibility = "hidden"; });
    img.addEventListener("load", () => { img.style.visibility = ""; });
    img.src = r.images[0];
    $(".img-count", el).textContent = r.images.length > 1 ? `1/${r.images.length}` : "";
    img.addEventListener("click", () => {
      i = (i + 1) % r.images.length;
      img.src = r.images[i];
      $(".img-count", el).textContent = `${i + 1}/${r.images.length}`;
    });
  } else img.remove();

  $(".place", el).textContent = r.neighborhood || r.street || r.title || "דירה";
  $(".street", el).textContent = [r.street, r.city].filter(Boolean).join(", ");
  const s = r.match_score ?? 0;
  $(".score-num", el).textContent = `${s}%`;
  $(".score", el).classList.add(s >= 85 ? "high" : s < 60 ? "low" : "mid");
  $(".price", el).textContent = r.price != null ? `₪${fmt(r.price)}` : "מחיר לא ידוע";
  $(".facts", el).textContent = [
    r.rooms != null ? `${r.rooms} חדרים` : null,
    r.size_sqm != null ? `${r.size_sqm} מ"ר` : null,
    r.floor != null ? (r.floor <= 0 ? "קרקע" : `קומה ${r.floor}`) : null,
    r.is_broker === true ? "תיווך" : r.is_broker === false ? "ללא תיווך" : null,
  ].filter(Boolean).join(" · ");
  const ul = $(".breakdown", el);
  (r.score_breakdown || []).forEach(b => {
    const li = document.createElement("li");
    li.className = b.state;
    li.textContent = b.label;
    ul.appendChild(li);
  });
  const ai = r.ai_analysis;
  if (ai) {
    const bits = [ai.summary && `🤖 ${esc(ai.summary)}`,
      ...(ai.red_flags || []).map(f => `⚠️ ${esc(f)}`)].filter(Boolean);
    $(".ai", el).innerHTML = bits.join("<br>");
  }
  if (r.description) $(".desc p", el).textContent = r.description; else $(".desc", el).remove();
  $(".open", el).href = r.url;

  const save = $(".save", el), reject = $(".reject", el);
  if (view === "saved") { save.textContent = "↩︎ הסר משמורות"; }
  if (view === "rejected") { reject.textContent = "↩︎ החזר"; save.remove(); }
  save.addEventListener("click", () => setStatus(r.id, view === "saved" ? "NEW" : "SAVED", el));
  reject.addEventListener("click", () => setStatus(r.id, view === "rejected" ? "NEW" : "REJECTED", el));
  return el;
}

async function setStatus(id, status, el) {
  await api(`/api/listings/${id}/status`, { method: "POST", body: JSON.stringify({ status }) });
  el.remove();
  if (!$("#list").children.length) loadList();
  refreshSummary();
}

// ---------- header / scan ----------
function searchChips(st) {
  const s = st.search, p = st.preferences;
  const rooms = s.min_rooms === s.max_rooms ? `${s.min_rooms} חדרים` : `${s.min_rooms || 0}–${s.max_rooms || "∞"} חדרים`;
  const chips = [s.city, rooms, `עד ₪${fmt(s.max_price)}`, s.min_size ? `${s.min_size}+ מ"ר` : null,
    (st.areas || []).map(a => a.name).join(" + ") || null,
    p.roommates ? `${p.roommates} שותפים` : null, s.exclude_ground_floor ? "בלי קרקע" : null].filter(Boolean);
  $("#search-summary").innerHTML = chips.map(c => `<span>${esc(c)}</span>`).join("");
}

async function refreshSummary() {
  const s = await api("/api/summary");
  const parts = [];
  if (s.excellent) parts.push(`${s.excellent} התאמות מצוינות`);
  if (s.good) parts.push(`${s.good} טובות`);
  if (s.possible) parts.push(`${s.possible} אפשריות`);
  $("#headline").innerHTML = s.new
    ? `🔥 ${s.new} דירות חדשות<small>${parts.join(" · ")}</small>`
    : s.total ? `${s.total} דירות מתאימות<small>${parts.join(" · ")}</small>` : "הסוכן מחפש לך דירה";
  const btn = $("#scan-btn");
  btn.disabled = s.scanning;
  btn.textContent = s.scanning ? "⏳ סורק…" : "🔍 סרוק עכשיו";
  const info = [];
  if (s.last_scan?.finished_at) info.push(`סריקה אחרונה: ${new Date(s.last_scan.finished_at).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" })}`);
  if (s.last_scan?.error) info.push(`⚠️ יד2 לא זמין כרגע — ננסה שוב בסריקה הבאה`);
  if (s.next_scan_at && !s.scanning) info.push(`הבאה: ${new Date(s.next_scan_at * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" })}`);
  if (!s.telegram) info.push("טלגרם לא מחובר (ראה README)");
  $("#scan-info").textContent = info.join(" · ");
  if (wasScanning && !s.scanning && view !== "settings") loadList();
  wasScanning = s.scanning;
  return s;
}

$("#scan-btn").addEventListener("click", async () => {
  if (STATIC) {
    if (STATIC.repo) window.open(`https://github.com/${STATIC.repo}/actions/workflows/hunt.yml`, "_blank");
    return;
  }
  await api("/api/scan", { method: "POST" });
  wasScanning = true;
  $("#scan-btn").disabled = true;
  $("#scan-btn").textContent = "⏳ סורק…";
});

async function poll() {
  try { const s = await refreshSummary(); setTimeout(poll, s.scanning || wasScanning ? 3000 : 20000); }
  catch { setTimeout(poll, 20000); }
}

// ---------- settings ----------
function renderStaticSettings() {
  const s = settings.search, p = settings.preferences, n = settings.notifications;
  const places = (settings.areas || []).map(g => `<li><b>${esc(g.name)}:</b> ${esc((g.places || []).join(", "))}</li>`).join("");
  const bot = STATIC.bot ? `<a class="primary" href="https://t.me/${esc(STATIC.bot)}" target="_blank" rel="noopener">פתח את הבוט בטלגרם</a>` : "";
  $("#settings").innerHTML = `<form onsubmit="return false">
    <fieldset><legend>מה אני מחפש עכשיו</legend><ul>
      <li>${esc(s.city)} · ${s.min_rooms === s.max_rooms ? s.min_rooms : `${s.min_rooms}–${s.max_rooms}`} חדרים</li>
      <li>מחיר: מ-₪${fmt(s.min_price || 0)} עד ₪${fmt(s.max_price)} · מינימום ${s.min_size || 0} מ"ר</li>
      <li>קומת קרקע: ${s.exclude_ground_floor ? "לא" : "כן"} · ${p.roommates} שותפים · התראה מציון ${n.min_score}</li>
    </ul><ul>${places}</ul></fieldset>
    <fieldset><legend>איך משנים</legend>
      <p class="muted">שולחים הודעה לבוט בטלגרם, והשינוי נכנס לתוקף בסריקה הבאה (עד כ-10 דקות):</p>
      <ul>
        <li><b>תקציב 13000</b></li><li><b>חדרים 4</b> או <b>חדרים 3.5-5</b></li><li><b>גודל 80</b></li>
        <li><b>בלי קרקע</b> / <b>אפשר קרקע</b></li><li><b>הוסף אזור אילת</b> / <b>הסר אזור אילת</b> (שכונה או רחוב)</li>
        <li><b>ציון 70</b> — ציון מינימלי להתראה</li><li><b>הגדרות</b> · <b>שמורות</b> · <b>עזרה</b></li>
      </ul><p class="muted">אפשר כמה פקודות בהודעה אחת, כל אחת בשורה נפרדת.</p>${bot}
    </fieldset></form>`;
}

function renderSettings() {
  if (STATIC) return renderStaticSettings();
  const st = structuredClone(settings);
  const s = st.search, p = st.preferences, n = st.notifications;
  const num = (path, label, v, step = 1) => `<label>${label}<input type="number" step="${step}" data-path="${path}" value="${v ?? ""}"></label>`;
  const sel = (path, label, v, opts) => `<label>${label}<select data-path="${path}">${opts.map(([k, t]) => `<option value="${k}" ${k === v ? "selected" : ""}>${t}</option>`).join("")}</select></label>`;
  const pref = [["preferred", "מועדף"], ["ignore", "לא משנה"]];
  $("#settings").innerHTML = `
  <form>
    <fieldset><legend>חיפוש</legend><div class="grid">
      <label>עיר<input data-path="search.city" value="${esc(s.city)}"></label>
      ${num("search.min_rooms", "מינימום חדרים", s.min_rooms, .5)}
      ${num("search.max_rooms", "מקסימום חדרים", s.max_rooms, .5)}
      ${num("search.max_price", "מחיר מקסימלי ₪", s.max_price, 100)}
      ${num("search.min_size", 'מינימום מ"ר', s.min_size)}
      ${sel("search.area_mode", "אזורים", s.area_mode, [["require", "רק באזורים שלי"], ["prefer", "העדף, אבל הראה הכל"]])}
      <label class="check"><input type="checkbox" data-path="search.exclude_ground_floor" ${s.exclude_ground_floor ? "checked" : ""}> בלי קומת קרקע</label>
    </div></fieldset>
    <fieldset><legend>אזורים ושכונות</legend><div id="areas"></div>
      <button type="button" class="link" id="add-group">+ קבוצת אזורים חדשה</button></fieldset>
    <fieldset><legend>העדפות</legend><div class="grid">
      ${num("preferences.roommates", "מספר שותפים", p.roommates)}
      ${sel("preferences.balcony", "מרפסת", p.balcony, pref)}
      ${sel("preferences.parking", "חניה", p.parking, pref)}
      ${sel("preferences.elevator", "מעלית", p.elevator, pref)}
      ${sel("preferences.broker", "תיווך", p.broker, [["allowed_not_preferred", "אפשרי, עדיף בלי"], ["ignore", "לא משנה"]])}
    </div></fieldset>
    <fieldset><legend>התראות וסריקה</legend><div class="grid">
      ${num("notifications.min_score", "ציון מינימלי להתראה", n.min_score)}
      ${num("notifications.max_per_scan", "מקסימום התראות לסריקה", n.max_per_scan)}
      ${num("schedule.scan_interval_minutes", "סריקה כל (דקות, מינ׳ 5)", st.schedule.scan_interval_minutes)}
      <label class="check"><input type="checkbox" data-path="notifications.telegram_enabled" ${n.telegram_enabled ? "checked" : ""}> התראות טלגרם</label>
      <label class="check"><input type="checkbox" data-path="ai.enabled" ${st.ai.enabled ? "checked" : ""}> ניתוח AI (Gemini)</label>
    </div></fieldset>
    <fieldset><legend>משקלות הציון</legend><div class="grid">
      ${Object.entries(st.scoring).map(([k, v]) => num(`scoring.${k}`, { price: "מחיר", area: "אזור", rooms: "חדרים", size: "גודל", floor: "קומה", balcony: "מרפסת", parking: "חניה", roommate_fit: "התאמה לשותפים", no_broker: "ללא תיווך", condition: "מצב הדירה", elevator: "מעלית" }[k] || k, v)).join("")}
    </div></fieldset>
    <div class="save-bar"><button class="primary" type="submit">שמור הגדרות</button><span class="toast"></span></div>
  </form>`;
  const areas = st.areas || [];
  const drawAreas = () => {
    $("#areas").innerHTML = "";
    areas.forEach((g, gi) => {
      const div = document.createElement("div");
      div.className = "area-group";
      div.innerHTML = `<div class="head"><input value="${esc(g.name)}"><button type="button" class="link">מחק קבוצה</button></div>
        <div class="chips">${(g.places || []).map((p, pi) => `<span class="chip">${esc(p)}<button type="button" data-pi="${pi}">✕</button></span>`).join("")}</div>
        <div class="add-row"><input placeholder="הוסף שכונה או רחוב (בעברית, כמו ביד2)"><button type="button">הוסף</button></div>`;
      $(".head input", div).addEventListener("input", e => g.name = e.target.value);
      $(".head button", div).addEventListener("click", () => { areas.splice(gi, 1); drawAreas(); });
      div.querySelectorAll(".chip button").forEach(b => b.addEventListener("click", () => { g.places.splice(+b.dataset.pi, 1); drawAreas(); }));
      const inp = $(".add-row input", div);
      const add = () => { const v = inp.value.trim(); if (v) { (g.places ||= []).push(v); drawAreas(); } };
      $(".add-row button", div).addEventListener("click", add);
      inp.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); add(); } });
      $("#areas").appendChild(div);
    });
  };
  drawAreas();
  $("#add-group").addEventListener("click", () => { areas.push({ name: "אזור חדש", places: [] }); drawAreas(); });

  $("#settings form").addEventListener("submit", async e => {
    e.preventDefault();
    const patch = { areas };
    e.target.querySelectorAll("[data-path]").forEach(inp => {
      const [sec, key] = inp.dataset.path.split(".");
      const val = inp.type === "checkbox" ? inp.checked : inp.type === "number" ? (inp.value === "" ? null : Number(inp.value)) : inp.value;
      (patch[sec] ||= {})[key] = val;
    });
    settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(patch) });
    searchChips(settings);
    $(".toast").textContent = "✓ נשמר — הציונים חושבו מחדש";
  });
}

// ---------- boot ----------
(async () => {
  try {
    const r = await fetch("data.json", { cache: "no-store" });
    if (r.ok) STATIC = await r.json();
  } catch {}
  if (STATIC) {
    $("#scan-btn").textContent = "🔄 סרוק עכשיו";
    if (!STATIC.repo) $("#scan-btn").hidden = true;
  }
  settings = await api("/api/settings");
  searchChips(settings);
  await loadList();
  poll();
})();

// ---------- search wizard: one question per screen ----------
const WIZ_KEY = "hunter-wizard-done";
function openWizard() {
  const s = settings.search, p = settings.preferences;
  const a = {
    places: (settings.areas || []).flatMap(g => g.places || []),
    rooms: s.min_rooms || 4, more: !s.max_rooms || s.max_rooms > s.min_rooms,
    price: s.max_price || 12000, size: s.min_size || 0, ground: !s.exclude_ground_floor,
    roommates: p.roommates || 1,
    wants: ["balcony", "parking", "elevator"].filter(k => p[k] === "preferred"),
  };
  const suggestions = [...new Set([...a.places, ...((STATIC && STATIC.neighborhoods) || [])])];
  const steps = [
    { q: "איפה לחפש?", hint: "בחר שכונות או רחובות. אפשר גם להקליד.", render: el => {
      el.innerHTML = `<input class="big" placeholder="הקלד שכונה או רחוב ולחץ Enter"><div class="opts"></div>`;
      const draw = () => { $(".opts", el).innerHTML = suggestions.map(x => `<button class="opt ${a.places.includes(x) ? "on" : ""}">${esc(x)}</button>`).join("");
        el.querySelectorAll(".opt").forEach((b, i) => b.onclick = () => { const x = suggestions[i]; a.places = a.places.includes(x) ? a.places.filter(y => y !== x) : [...a.places, x]; draw(); }); };
      $("input", el).onkeydown = e => { if (e.key === "Enter" && e.target.value.trim()) { const x = e.target.value.trim(); if (!suggestions.includes(x)) suggestions.unshift(x); if (!a.places.includes(x)) a.places.push(x); e.target.value = ""; draw(); } };
      draw(); }, ok: () => a.places.length > 0 },
    { q: "כמה חדרים?", hint: "", render: el => choice(el, [2, 2.5, 3, 3.5, 4, 4.5, 5, 6], a.rooms, v => a.rooms = v, x => `${x}`, () =>
        `<label class="check" style="margin-top:14px"><input type="checkbox" ${a.more ? "checked" : ""}> גם יותר חדרים</label>`, box => box.onchange = e => a.more = e.target.checked) },
    { q: "מה התקציב החודשי?", hint: "מחיר מקסימלי בשקלים", render: el => {
      el.innerHTML = `<input class="big" type="number" inputmode="numeric" step="100" value="${a.price}"><div class="opts"></div>`;
      $("input", el).oninput = e => a.price = Number(e.target.value);
      $(".opts", el).innerHTML = [6000, 8000, 10000, 12000, 15000].map(v => `<button class="opt">₪${fmt(v)}</button>`).join("");
      el.querySelectorAll(".opt").forEach((b, i) => b.onclick = () => { a.price = [6000, 8000, 10000, 12000, 15000][i]; $("input", el).value = a.price; }); },
      ok: () => a.price >= 1000 },
    { q: "מה הגודל המינימלי?", hint: 'במ"ר', render: el => choice(el, [0, 50, 60, 70, 80, 90, 100], a.size, v => a.size = v, x => x ? `${x}+` : "לא משנה") },
    { q: "קומת קרקע מתאימה?", hint: "", render: el => choice(el, [true, false], a.ground, v => a.ground = v, x => x ? "כן, אפשר" : "לא, בלי קרקע") },
    { q: "כמה אנשים יגורו בדירה?", hint: "כולל אותך", render: el => choice(el, [1, 2, 3, 4, 5], a.roommates, v => a.roommates = v, x => x === 1 ? "רק אני" : `${x}`) },
    { q: "מה חשוב לך?", hint: "אפשר לבחור כמה, או כלום", render: el => {
      const names = { balcony: "🌿 מרפסת", parking: "🅿️ חניה", elevator: "🛗 מעלית" };
      const draw = () => { el.innerHTML = `<div class="opts">${Object.keys(names).map(k => `<button class="opt ${a.wants.includes(k) ? "on" : ""}" data-k="${k}">${names[k]}</button>`).join("")}</div>`;
        el.querySelectorAll(".opt").forEach(b => b.onclick = () => { const k = b.dataset.k; a.wants = a.wants.includes(k) ? a.wants.filter(x => x !== k) : [...a.wants, k]; draw(); }); };
      draw(); } },
    { q: "זה מה שאחפש בשבילך", hint: "", summary: true, render: el => {
      el.innerHTML = `<ul class="wz-summary">
        <li>📍 ${esc(a.places.join(", "))}</li>
        <li>🛏 ${a.rooms}${a.more ? "+" : ""} חדרים</li>
        <li>💰 עד ₪${fmt(a.price)}</li>
        <li>📐 ${a.size ? `לפחות ${a.size} מ"ר` : "כל גודל"}</li>
        <li>🏢 ${a.ground ? "כולל קומת קרקע" : "בלי קומת קרקע"}</li>
        <li>👥 ${a.roommates === 1 ? "רק אני" : `${a.roommates} אנשים`}</li>
        <li>⭐ ${a.wants.length ? a.wants.map(k => ({ balcony: "מרפסת", parking: "חניה", elevator: "מעלית" }[k])).join(", ") : "בלי העדפות מיוחדות"}</li>
      </ul>${STATIC ? `<p class="wz-note">בלחיצה על "שמור" ייפתח הבוט בטלגרם עם ההגדרות מוכנות. לחץ שם על שליחה, והחיפוש יתעדכן תוך כ-10 דקות.</p>` : ""}`; } },
  ];

  function choice(el, values, current, set, label, extra, bindExtra) {
    const draw = cur => {
      el.innerHTML = `<div class="opts">${values.map((v, i) => `<button class="opt ${v === cur ? "on" : ""}" data-i="${i}">${label(v)}</button>`).join("")}</div>${extra ? extra() : ""}`;
      el.querySelectorAll(".opt").forEach(b => b.onclick = () => { set(values[+b.dataset.i]); draw(values[+b.dataset.i]); });
      if (bindExtra) bindExtra($("input[type=checkbox]", el));
    };
    draw(current);
  }

  function commands() {
    return [
      `קבע אזורים: ${a.places.join(", ")}`,
      `חדרים ${a.rooms}${a.more ? "-10" : ""}`,
      `תקציב ${a.price}`,
      `גודל ${a.size}`,
      a.ground ? "אפשר קרקע" : "בלי קרקע",
      `שותפים ${a.roommates}`,
      ...["balcony", "parking", "elevator"].map(k => `${{ balcony: "מרפסת", parking: "חניה", elevator: "מעלית" }[k]} ${a.wants.includes(k) ? "חשוב" : "לא משנה"}`),
    ].join("\n");
  }

  async function finish() {
    try { localStorage.setItem(WIZ_KEY, "1"); } catch {}
    if (!STATIC) {
      settings = await api("/api/settings", { method: "PUT", body: JSON.stringify({
        areas: [{ name: "האזורים שלי", places: a.places }],
        search: { min_rooms: a.rooms, max_rooms: a.more ? 10 : a.rooms, max_price: a.price, min_size: a.size, exclude_ground_floor: !a.ground },
        preferences: { roommates: a.roommates, balcony: a.wants.includes("balcony") ? "preferred" : "ignore",
          parking: a.wants.includes("parking") ? "preferred" : "ignore", elevator: a.wants.includes("elevator") ? "preferred" : "ignore" } }) });
      searchChips(settings); close(); loadList(); return;
    }
    const text = commands();
    try { await navigator.clipboard.writeText(text); } catch {}
    if (STATIC.bot) window.location.href = `https://t.me/${STATIC.bot}?text=${encodeURIComponent(text)}`;
    close();
  }

  const box = $("#wizard");
  let i = 0;
  const close = () => { box.hidden = true; document.body.style.overflow = ""; };
  function show() {
    const st = steps[i];
    box.innerHTML = `<div class="wz">
      <div class="wz-top"><span class="muted">${i + 1} / ${steps.length}</span><button class="ghost" data-x>✕</button></div>
      <div class="wz-progress"><div style="width:${100 * (i + 1) / steps.length}%"></div></div>
      <h2>${st.q}</h2>${st.hint ? `<p class="hint">${st.hint}</p>` : ""}
      <div class="wz-body"></div>
      <div class="wz-nav">${i ? `<button class="ghost" data-back>→ חזרה</button>` : ""}<button class="primary" data-next>${st.summary ? "✓ שמור את החיפוש" : "הבא ←"}</button></div>
    </div>`;
    st.render($(".wz-body", box));
    $("[data-x]", box).onclick = () => { try { localStorage.setItem(WIZ_KEY, "1"); } catch {} close(); };
    if (i) $("[data-back]", box).onclick = () => { i--; show(); };
    $("[data-next]", box).onclick = () => {
      if (st.ok && !st.ok()) return;
      if (st.summary) finish(); else { i++; show(); }
    };
    box.scrollTop = 0;
  }
  box.hidden = false;
  document.body.style.overflow = "hidden";
  show();
}

$("#wizard-btn").addEventListener("click", () => settings && openWizard());
(async function firstVisit() {
  // Open the wizard once for first-time visitors (after boot has loaded settings).
  for (let n = 0; n < 50 && !settings; n++) await new Promise(r => setTimeout(r, 100));
  let seen = false;
  try { seen = !!localStorage.getItem(WIZ_KEY); } catch { seen = true; }
  if (settings && !seen) openWizard();
})();

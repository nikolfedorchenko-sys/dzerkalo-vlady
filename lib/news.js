// Спільне для серверних функцій сайту (папка functions/): читання news.json,
// дати за Києвом, екранування й перетворення тексту новини на HTML.

export const SITE = "https://dzerkalo-vlady.com";
export const SITE_NAME = "Дзеркало влади";
export const SLOGAN = "Влада – без фільтрів. Дивись, що вирішують за тебе.";
export const LOGO = SITE + "/assets/logos/dv-avatar-640.png";

export const RUBRICS = {
  "kyivrada": "Київрада",
  "verkhovna-rada": "Верховна Рада",
  "uriad": "Уряд",
  "ofis-prezydenta": "Офіс президента",
  "rozsliduvannia": "Розслідування",
  "hroshi": "Гроші",
  "misto": "Місто",
  "perevirka-faktiv": "Перевірка фактів",
  "dumka": "Думка",
};

/* Усі новини з data/news.json, найновіші першими. */
export async function loadNews(context) {
  const res = await context.env.ASSETS.fetch(new URL("/data/news.json", context.request.url));
  if (!res.ok) throw new Error("news.json: " + res.status);
  const data = await res.json();
  return (data.news || [])
    .filter((n) => n && n.id && n.title)
    .sort((a, b) => kyivDate(b.date) - kyivDate(a.date));
}

export function articleUrl(n) {
  return SITE + "/article?id=" + encodeURIComponent(n.id);
}

export function photoUrl(n) {
  const f = n.photo && n.photo.file;
  if (!f) return "";
  return /^https?:\/\//i.test(f) ? f : SITE + "/" + f.replace(/^\/+/, "");
}

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

/* Прибирає розмітку посилань [текст](адреса) – для description і RSS-анонсу. */
export function plain(s) {
  return String(s == null ? "" : s).replace(/\[([^\[\]]+)\]\(([^)\s]+)\)/g, "$1");
}

function safeUrl(u) {
  u = String(u || "").trim();
  if (/^(https?:\/\/|mailto:)/i.test(u)) return u;
  if (u && u.indexOf(":") === -1) return SITE + "/" + u.replace(/^\/+/, "");
  return "";
}

/* Абзац: екрануємо, [текст](адреса) – посилання (як у js/main.js). */
export function inline(s) {
  return esc(s).replace(/\[([^\[\]]+)\]\(([^)\s]+)\)/g, (m, text, url) => {
    const u = safeUrl(url.replace(/&amp;/g, "&"));
    return u ? '<a href="' + esc(u) + '">' + text + "</a>" : m;
  });
}

/* Текст статті як простий HTML: абзаци, підзаголовки, цитати, «що це означає», думка, джерела. */
export function bodyHTML(n) {
  const blocks = Array.isArray(n.body) ? n.body : (n.body ? [n.body] : []);
  const out = [];
  if (n.verdict && n.verdict.label) {
    out.push("<p><strong>Вердикт: " + esc(n.verdict.label) + ".</strong> " +
      (n.verdict.claim ? "Твердження: " + inline(n.verdict.claim) + " " : "") + inline(n.verdict.text || "") + "</p>");
  }
  const impact = n.impact && n.impact.text
    ? "<p><strong>" + esc(n.impact.label || "Що це означає для тебе") + ":</strong> " + inline(n.impact.text) + "</p>" : "";
  blocks.forEach((b, i) => {
    if (typeof b === "string") out.push("<p>" + inline(b) + "</p>");
    else if (b && b.h2) out.push("<h2>" + inline(b.h2) + "</h2>");
    else if (b && b.quote) {
      out.push("<blockquote><p>«" + esc(String(b.quote).replace(/^«|»$/g, "")) + "»</p>" +
        (b.who ? "<footer>" + esc(b.who) + "</footer>" : "") + "</blockquote>");
    }
    if (i === 0 && impact) out.push(impact);
  });
  if (!blocks.length && impact) out.push(impact);
  if (n.opinion) out.push("<h2>Думка редакції</h2><p>" + inline(n.opinion) + "</p>");
  const sources = (n.sources || []).filter((s) => s && s.title);
  if (sources.length) {
    out.push("<h2>Джерела</h2><ol>" + sources.map((s) => {
      const u = safeUrl(s.url);
      return "<li>" + (u ? '<a href="' + esc(u) + '">' + esc(s.title) + "</a>" : esc(s.title)) + "</li>";
    }).join("") + "</ol>");
  }
  return out.join("");
}

/* ---------- дати ----------
   У news.json час київський без поясу: «2026-10-09T09:55» або «2026-10-09».
   Київ: +03:00 з останньої неділі березня до останньої неділі жовтня (перехід о 01:00 UTC), інакше +02:00. */
function lastSunday(year, month) { // month: 0–11
  const d = new Date(Date.UTC(year, month + 1, 0));
  d.setUTCDate(d.getUTCDate() - d.getUTCDay());
  return d;
}

function parts(s) {
  const m = String(s || "").match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/);
  if (!m) return null;
  return { y: +m[1], mo: +m[2] - 1, d: +m[3], h: m[4] ? +m[4] : 0, mi: m[5] ? +m[5] : 0 };
}

/* Справжній момент часу (Date) для київського часу з news.json. */
export function kyivDate(s) {
  const p = parts(s);
  if (!p) return new Date(0);
  const naive = Date.UTC(p.y, p.mo, p.d, p.h, p.mi);
  const start = lastSunday(p.y, 2).getTime() + 3600e3;  // 01:00 UTC
  const end = lastSunday(p.y, 9).getTime() + 3600e3;
  const summer = naive - 3 * 3600e3 >= start && naive - 3 * 3600e3 < end;
  return new Date(naive - (summer ? 3 : 2) * 3600e3);
}

/* «2026-10-09T09:55:00+03:00» – для og/JSON-LD/sitemap. */
export function isoDate(s) {
  const p = parts(s);
  if (!p) return "";
  const t = kyivDate(s);
  const off = Math.round((Date.UTC(p.y, p.mo, p.d, p.h, p.mi) - t.getTime()) / 3600e3);
  const pad = (x) => (x < 10 ? "0" : "") + x;
  return p.y + "-" + pad(p.mo + 1) + "-" + pad(p.d) + "T" + pad(p.h) + ":" + pad(p.mi) + ":00+0" + off + ":00";
}

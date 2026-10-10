// Карта сайту для Google: /sitemap.xml. Будується з data/news.json щоразу заново.
// Новини за останні 2 доби додатково позначені для Google Новин (news:news).
import { SITE, SITE_NAME, RUBRICS, loadNews, articleUrl, photoUrl, esc, isoDate, kyivDate } from "../lib/news.js";

export async function onRequestGet(context) {
  const news = await loadNews(context);
  const now = Date.now();
  const latest = news[0] ? isoDate(news[0].date) : "";

  const pages = [
    { loc: SITE + "/", lastmod: latest, priority: "1.0" },
    { loc: SITE + "/rubric", lastmod: latest },
    ...Object.keys(RUBRICS).map((slug) => ({ loc: SITE + "/rubric?r=" + slug })),
    { loc: SITE + "/about" },
  ].map((p) => "<url><loc>" + esc(p.loc) + "</loc>" + (p.lastmod ? "<lastmod>" + p.lastmod + "</lastmod>" : "") + "</url>");

  const articles = news.map((n) => {
    const fresh = now - kyivDate(n.date).getTime() < 2 * 86400e3;
    const img = photoUrl(n);
    return "<url><loc>" + esc(articleUrl(n)) + "</loc><lastmod>" + isoDate(n.updated || n.date) + "</lastmod>" +
      (fresh ? "<news:news><news:publication><news:name>" + SITE_NAME + "</news:name><news:language>uk</news:language></news:publication>" +
        "<news:publication_date>" + isoDate(n.date) + "</news:publication_date><news:title>" + esc(n.title) + "</news:title></news:news>" : "") +
      (img ? "<image:image><image:loc>" + esc(img) + "</image:loc></image:image>" : "") +
      "</url>";
  });

  const xml = '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">\n' +
    pages.concat(articles).join("\n") + "\n</urlset>\n";
  return new Response(xml, { headers: { "Content-Type": "application/xml; charset=utf-8", "Cache-Control": "public, max-age=600" } });
}

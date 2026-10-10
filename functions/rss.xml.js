// RSS-стрічка /rss.xml – для UKR.NET, Google Новин, читалок і агрегаторів.
// Повний текст статті – у content:encoded, фото – у enclosure.
import { SITE, SITE_NAME, SLOGAN, LOGO, RUBRICS, loadNews, articleUrl, photoUrl, esc, plain, bodyHTML, kyivDate } from "../lib/news.js";

const TYPES = { jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", gif: "image/gif" };

export async function onRequestGet(context) {
  const news = (await loadNews(context)).slice(0, 50);
  const cdata = (s) => "<![CDATA[" + String(s).replace(/]]>/g, "]]]]><![CDATA[>") + "]]>";

  const items = news.map((n) => {
    const url = articleUrl(n);
    const img = photoUrl(n);
    const ext = img ? img.split(".").pop().toLowerCase() : "";
    const section = RUBRICS[n.rubric];
    return "<item>" +
      "<title>" + esc(n.title) + "</title>" +
      "<link>" + esc(url) + "</link>" +
      '<guid isPermaLink="true">' + esc(url) + "</guid>" +
      "<pubDate>" + kyivDate(n.date).toUTCString() + "</pubDate>" +
      (section ? "<category>" + esc(section) + "</category>" : "") +
      (n.author ? "<dc:creator>" + esc(n.author) + "</dc:creator>" : "") +
      "<description>" + esc(plain(n.lead || "")) + "</description>" +
      "<content:encoded>" + cdata((n.lead ? "<p>" + esc(plain(n.lead)) + "</p>" : "") + bodyHTML(n)) + "</content:encoded>" +
      (img ? '<enclosure url="' + esc(img) + '" type="' + (TYPES[ext] || "image/jpeg") + '" length="0"/>' : "") +
      "</item>";
  });

  const xml = '<?xml version="1.0" encoding="UTF-8"?>\n' +
    '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>' +
    "<title>" + SITE_NAME + "</title><link>" + SITE + "/</link>" +
    "<description>" + esc(SLOGAN) + "</description><language>uk</language>" +
    '<atom:link href="' + SITE + '/rss.xml" rel="self" type="application/rss+xml"/>' +
    "<image><url>" + LOGO + "</url><title>" + SITE_NAME + "</title><link>" + SITE + "/</link></image>" +
    (news[0] ? "<lastBuildDate>" + kyivDate(news[0].date).toUTCString() + "</lastBuildDate>" : "") +
    "\n" + items.join("\n") + "\n</channel>\n</rss>\n";
  return new Response(xml, { headers: { "Content-Type": "application/rss+xml; charset=utf-8", "Cache-Control": "public, max-age=600" } });
}

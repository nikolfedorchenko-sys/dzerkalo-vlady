// Головна «/»: у стрічку одразу дописуємо посилання на 30 свіжих новин,
// щоб Google знаходив нові матеріали з першого ж читання сторінки, не чекаючи js/main.js.
import { loadNews, linksHTML } from "../lib/news.js";

export async function onRequestGet(context) {
  const page = await context.next();
  try {
    const news = (await loadNews(context)).slice(0, 30);
    return new HTMLRewriter()
      .on("#feed-list", { element(el) { el.setInnerContent(linksHTML(news), { html: true }); } })
      .transform(page);
  } catch (e) {
    console.log("index: " + e.message);
    return page;
  }
}

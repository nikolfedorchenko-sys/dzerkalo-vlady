// Сторінка рубрики /rubric?r=… : свій заголовок, опис і canonical для кожної рубрики
// та посилання на її новини для пошуковиків. Пошук (/rubric?q=…) не індексується.
import { SITE, SITE_NAME, RUBRICS, loadNews, esc, linksHTML } from "../lib/news.js";

export async function onRequestGet(context) {
  const page = await context.next();
  try {
    const params = new URL(context.request.url).searchParams;
    const slug = RUBRICS[params.get("r")] ? params.get("r") : "";
    const name = slug ? RUBRICS[slug] : "Усі новини";
    const url = SITE + "/rubric" + (slug ? "?r=" + slug : "");
    const description = slug
      ? "Рубрика «" + name + "» – рішення влади та їхні наслідки людською мовою. Кожен факт – з джерелом."
      : "Усі новини «Дзеркала влади»: Київрада, Верховна Рада, уряд, Офіс президента, гроші, місто.";
    const news = (await loadNews(context)).filter((n) => !slug || n.rubric === slug).slice(0, 50);
    const setContent = (value) => ({ element(el) { el.setAttribute("content", value); } });
    const head = params.get("q")
      ? '<meta name="robots" content="noindex, follow">'
      : '<link rel="canonical" href="' + esc(url) + '"><meta property="og:url" content="' + esc(url) + '">';

    return new HTMLRewriter()
      .on("title", { element(el) { el.setInnerContent(name + " – " + SITE_NAME); } })
      .on('meta[name="description"]', setContent(description))
      .on('meta[property="og:title"]', setContent(name + " – " + SITE_NAME))
      .on('meta[property="og:description"]', setContent(description))
      .on("head", { element(el) { el.append(head, { html: true }); } })
      .on("#rubric", { element(el) { el.setInnerContent("<h1>" + esc(name) + "</h1><nav>" + linksHTML(news) + "</nav>", { html: true }); } })
      .transform(page);
  } catch (e) {
    console.log("rubric: " + e.message);
    return page;
  }
}

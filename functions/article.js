// Сторінка статті /article?id=… : до звичайного article.html сервер дописує заголовок, опис
// і фото саме цієї новини (прев'ю у Facebook, Telegram, Google) і сам текст статті –
// його бачать пошуковики, а для читача js/main.js потім малює сторінку як завжди.
import { SITE, SITE_NAME, LOGO, RUBRICS, loadNews, articleUrl, photoUrl, esc, plain, inline, bodyHTML, isoDate } from "../lib/news.js";

export async function onRequestGet(context) {
  const page = await context.next();
  try {
    const id = new URL(context.request.url).searchParams.get("id");
    if (!id) return notFound(page);
    const news = await loadNews(context);
    const n = news.find((x) => x.id === id);
    if (!n) return notFound(page);
    return withArticle(page, n);
  } catch (e) {
    console.log("article: " + e.message);
    return page;
  }
}

function notFound(page) {
  const res = new HTMLRewriter()
    .on("head", { element(el) { el.append('<meta name="robots" content="noindex">', { html: true }); } })
    .transform(page);
  return new Response(res.body, { status: 404, headers: res.headers });
}

function withArticle(page, n) {
  const title = n.title;
  const description = plain(n.lead || "").replace(/\s+/g, " ").trim().slice(0, 300);
  const url = articleUrl(n);
  const image = photoUrl(n) || LOGO;
  const published = isoDate(n.date);
  const section = RUBRICS[n.rubric] || "";

  const setContent = (value) => ({ element(el) { el.setAttribute("content", value); } });

  const ld = {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    headline: title.slice(0, 110),
    description,
    image: [image],
    datePublished: published,
    dateModified: isoDate(n.updated || n.date),
    author: [n.author ? { "@type": "Person", name: n.author } : { "@type": "Organization", name: SITE_NAME, url: SITE }],
    publisher: { "@type": "Organization", name: SITE_NAME, url: SITE, logo: { "@type": "ImageObject", url: LOGO } },
    mainEntityOfPage: url,
    inLanguage: "uk",
  };
  if (section) ld.articleSection = section;

  const extraHead =
    '<link rel="canonical" href="' + esc(url) + '">' +
    '<meta property="og:url" content="' + esc(url) + '">' +
    (published ? '<meta property="article:published_time" content="' + esc(published) + '">' : "") +
    (section ? '<meta property="article:section" content="' + esc(section) + '">' : "") +
    (n.photo && n.photo.alt ? '<meta property="og:image:alt" content="' + esc(n.photo.alt) + '">' : "") +
    '<script type="application/ld+json">' + JSON.stringify(ld).replace(/</g, "\\u003c") + "</script>";

  return new HTMLRewriter()
    .on("title", { element(el) { el.setInnerContent(title + " – " + SITE_NAME); } })
    .on('meta[name="description"]', setContent(description))
    .on('meta[property="og:title"]', setContent(title))
    .on('meta[property="og:description"]', setContent(description))
    .on('meta[property="og:image"]', setContent(image))
    .on('meta[name="twitter:card"]', setContent(photoUrl(n) ? "summary_large_image" : "summary"))
    .on("head", { element(el) { el.append(extraHead, { html: true }); } })
    .on("#article", { element(el) { el.setInnerContent(articleHTML(n), { html: true }); } })
    .transform(page);
}

/* Полегшені фото, як у js/main.js: NAME-640.webp / NAME-1280.webp (tools/optimize_photos.py),
   а якщо їх немає – оригінал. */
function imgAttrs(file) {
  const m = String(file || "").match(/^(.*)\.(jpe?g|png)$/i);
  if (!m) return ' src="' + esc(file) + '"';
  const b = esc(m[1]);
  return ' src="' + b + '-1280.webp" srcset="' + b + "-640.webp 640w, " + b + '-1280.webp 1280w" sizes="(max-width: 800px) 100vw, 760px"' +
    " onerror=\"this.onerror=null;this.removeAttribute('srcset');this.src='" + esc(file) + "'\"";
}

/* Та сама розмітка, що малює js/main.js, тільки без кнопок – щоб сторінка не «стрибала». */
function articleHTML(n) {
  const k = n.kicker || RUBRICS[n.rubric] || "";
  const p = n.photo;
  const credit = p ? "Фото: " + [p.author, p.license].filter(Boolean).join(", ") : "";
  return '<article class="article">' +
    (k ? '<div><span class="label">' + esc(k) + "</span></div>" : "") +
    '<h1 class="article__title">' + esc(n.title) + "</h1>" +
    (n.lead ? '<p class="article__lead">' + inline(n.lead) + "</p>" : "") +
    (n.author ? '<div class="article__bar"><div class="meta"><strong>' + esc(n.author) + "</strong></div></div>" : "") +
    (p && p.file ? '<figure class="article__fig"><img' + imgAttrs(p.file) + ' alt="' + esc(p.alt) + '" width="1200" height="675" fetchpriority="high">' +
      "<figcaption>" + (p.caption ? esc(p.caption) + ". " : "") + esc(credit) + "</figcaption></figure>" : "") +
    '<div class="prose">' + bodyHTML(n) + "</div></article>";
}

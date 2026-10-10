/* Дзеркало влади – спільна шапка й підвал, рядок «Терміново»
   і побудова сторінок із data/news.json. Без бібліотек. */
(function () {
  'use strict';

  /* Рубрики сайту. slug – як рубрика пишеться в news.json і в адресі сторінки. */
  var RUBRICS = [
    { slug: 'kyivrada', name: 'Київрада' },
    { slug: 'verkhovna-rada', name: 'Верховна Рада' },
    { slug: 'uriad', name: 'Уряд' },
    { slug: 'ofis-prezydenta', name: 'Офіс президента' },
    { slug: 'rozsliduvannia', name: 'Розслідування' },
    { slug: 'hroshi', name: 'Гроші' },
    { slug: 'misto', name: 'Місто' },
    { slug: 'perevirka-faktiv', name: 'Перевірка фактів' },
    { slug: 'dumka', name: 'Думка' }
  ];
  /* Рубрики в меню шапки – як у затвердженому макеті. */
  var NAV = ['kyivrada', 'verkhovna-rada', 'uriad', 'rozsliduvannia', 'perevirka-faktiv', 'dumka'];

  var TELEGRAM = 'https://t.me/dzerkalo_vlady';
  var SEND_NEWS = 'about.html#contact';
  var MONTHS = ['січня', 'лютого', 'березня', 'квітня', 'травня', 'червня', 'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня'];
  var MONTHS_SHORT = ['січ', 'лют', 'бер', 'кві', 'тра', 'чер', 'лип', 'сер', 'вер', 'жов', 'лис', 'гру'];

  var ICON_SEARCH = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>';
  var ICON_MENU = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="4" y1="7" x2="20" y2="7"></line><line x1="4" y1="12" x2="20" y2="12"></line><line x1="4" y1="17" x2="20" y2="17"></line></svg>';
  var ICON_CLOSE = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18"></line><line x1="18" y1="6" x2="6" y2="18"></line></svg>';
  var ARROW = '<span class="btn__arrow"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="7" y1="17" x2="17" y2="7"></line><polyline points="8 7 17 7 17 16"></polyline></svg></span>';

  /* ---------- допоміжне ---------- */
  function $(sel) { return document.querySelector(sel); }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function safeUrl(u) {
    u = String(u || '').trim();
    if (/^(https?:\/\/|mailto:)/i.test(u)) return u;
    if (u && u.indexOf(':') === -1) return u; // відносне посилання на сторінку сайту
    return '';
  }

  /* Текст абзацу: екрануємо, а [текст](адреса) перетворюємо на посилання. */
  function inline(s) {
    return esc(s).replace(/\[([^\[\]]+)\]\(([^)\s]+)\)/g, function (m, text, url) {
      var u = safeUrl(url.replace(/&amp;/g, '&'));
      if (!u) return m;
      var ext = /^https?:/i.test(u) ? ' target="_blank" rel="noopener"' : '';
      return '<a href="' + esc(u) + '"' + ext + '>' + text + '</a>';
    });
  }

  function rubricName(slug) {
    for (var i = 0; i < RUBRICS.length; i++) if (RUBRICS[i].slug === slug) return RUBRICS[i].name;
    return '';
  }
  function rubricUrl(slug) { return slug ? 'rubric.html?r=' + encodeURIComponent(slug) : 'rubric.html'; }
  function articleUrl(n) { return 'article.html?id=' + encodeURIComponent(n.id); }

  /* Дата «2026-10-09T09:55» або «2026-10-09» – у місцевому часі. */
  function parseDate(s) {
    var parts = String(s || '').split('T');
    var d = (parts[0] || '').split('-').map(Number);
    var t = parts[1] ? parts[1].split(':').map(Number) : [0, 0];
    return { d: new Date(d[0] || 1970, (d[1] || 1) - 1, d[2] || 1, t[0] || 0, t[1] || 0), time: !!parts[1] };
  }
  function pad(x) { return (x < 10 ? '0' : '') + x; }
  function hhmm(d) { return pad(d.getHours()) + ':' + pad(d.getMinutes()); }
  function yearSuffix(d) { return d.getFullYear() !== new Date().getFullYear() ? ' ' + d.getFullYear() : ''; }
  function fmtDay(n) { var d = n._d.d; return d.getDate() + ' ' + MONTHS[d.getMonth()] + yearSuffix(d); }
  function fmtLong(n) { return fmtDay(n) + (n._d.time ? ', ' + hhmm(n._d.d) : ''); }
  function fmtFeed(n) {
    var d = n._d.d, now = new Date();
    var today = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
    if (today && n._d.time) return hhmm(d);
    return d.getDate() + ' ' + MONTHS_SHORT[d.getMonth()];
  }

  function plural(n, one, few, many) {
    var a = n % 10, b = n % 100;
    if (a === 1 && b !== 11) return one;
    if (a >= 2 && a <= 4 && (b < 12 || b > 14)) return few;
    return many;
  }

  /* «Терміново» діє, доки не настав час urgentUntil (якщо він вказаний) – тоді червоний рядок зникає сам. */
  function isUrgent(n) {
    if (!n.urgent) return false;
    return !n.urgentUntil || new Date() < parseDate(n.urgentUntil).d;
  }

  function credit(p) {
    if (!p) return '';
    return 'Фото: ' + [p.author, p.license].filter(Boolean).join(', ');
  }
  /* Фото: на телефон – NAME-640.webp, на комп'ютер – NAME-1280.webp (їх робить tools/optimize_photos.py).
     Якщо полегшених версій немає, браузер бере оригінал (onerror). */
  function imgAttrs(p, sizes) {
    var f = String(p.file || '');
    var m = f.match(/^(.*)\.(jpe?g|png)$/i);
    if (!m) return ' src="' + esc(f) + '"';
    var b = esc(m[1]);
    return ' src="' + b + '-1280.webp" srcset="' + b + '-640.webp 640w, ' + b + '-1280.webp 1280w" sizes="' + sizes + '"' +
      ' onerror="this.onerror=null;this.removeAttribute(\'srcset\');this.src=\'' + esc(f) + '\'"';
  }

  /* Яку частину фото показувати при обрізці: photo.position, напр. "50% 25%". */
  function pos(p) { return p && p.position ? ' style="object-position: ' + esc(p.position) + '"' : ''; }
  function kicker(n) { return n.kicker || rubricName(n.rubric); }

  /* ---------- шапка й підвал ---------- */
  function headerHTML() {
    var links = NAV.map(function (slug) {
      return '<a href="' + rubricUrl(slug) + '" data-rubric="' + slug + '">' + esc(rubricName(slug)) + '</a>';
    }).join('');
    return '<div class="container"><header class="header" id="header">' +
      '<a class="header__logo" href="index.html" aria-label="Дзеркало влади – на головну"><img src="assets/logos/dv-wordmark.svg" alt="Дзеркало влади" width="300" height="26"></a>' +
      '<nav class="nav" id="nav" aria-label="Рубрики">' + links + '<a class="nav__send" href="' + SEND_NEWS + '">Надіслати новину</a></nav>' +
      '<div class="header__actions">' +
      '<button type="button" class="icon-btn" id="search-btn" aria-label="Пошук" aria-expanded="false" aria-controls="search">' + ICON_SEARCH + '</button>' +
      '<a class="btn header__send" href="' + SEND_NEWS + '">Надіслати новину</a>' +
      '<button type="button" class="icon-btn menu-btn" id="menu-btn" aria-label="Відкрити меню" aria-expanded="false" aria-controls="nav">' + ICON_MENU + '</button>' +
      '</div>' +
      '<form class="search" id="search" action="rubric.html" role="search" hidden>' +
      '<label class="sr-only" for="q">Пошук новин</label>' +
      '<input id="q" name="q" type="search" placeholder="Пошук новин" autocomplete="off">' +
      '<button class="btn" type="submit">Шукати</button></form>' +
      '</header></div>';
  }

  function footerHTML() {
    var rubrics = RUBRICS.map(function (r) { return '<a href="' + rubricUrl(r.slug) + '">' + esc(r.name) + '</a>'; }).join('');
    return '<div class="footer__top">' +
      '<div class="footer__brand"><img src="assets/logos/dv-wordmark.svg" alt="Дзеркало влади" width="300" height="26">' +
      '<p>Незалежне медіа про владу в Україні. Кожен факт – з джерелом, кожна думка – підписана.</p></div>' +
      '<nav class="footer__nav" aria-label="Про медіа">' +
      '<a href="about.html">Про нас</a><a href="about.html#how">Редакційна політика</a>' +
      '<a href="' + SEND_NEWS + '">Надіслати новину</a><a href="about.html#contact">Реклама</a>' +
      '<a href="' + TELEGRAM + '">Telegram</a></nav>' +
      '<nav class="footer__nav footer__nav--rubrics" aria-label="Усі рубрики">' + rubrics + '</nav>' +
      '</div>' +
      '<div class="footer__bottom">© ' + new Date().getFullYear() + ' Дзеркало влади · Фото – Wikimedia Commons, автори й ліцензії вказані під кожним</div>';
  }

  function setActiveNav(slug) {
    var links = document.querySelectorAll('.nav a[data-rubric]');
    for (var i = 0; i < links.length; i++) {
      if (links[i].getAttribute('data-rubric') === slug) links[i].setAttribute('aria-current', 'page');
      else links[i].removeAttribute('aria-current');
    }
  }

  function initHeader() {
    var header = $('#header'), menuBtn = $('#menu-btn'), searchBtn = $('#search-btn'), search = $('#search');
    function setMenu(open) {
      header.classList.toggle('is-open', open);
      menuBtn.setAttribute('aria-expanded', String(open));
      menuBtn.setAttribute('aria-label', open ? 'Закрити меню' : 'Відкрити меню');
      menuBtn.innerHTML = open ? ICON_CLOSE : ICON_MENU;
    }
    menuBtn.addEventListener('click', function () { setMenu(!header.classList.contains('is-open')); });
    $('#nav').addEventListener('click', function (e) { if (e.target.closest('a')) setMenu(false); });
    searchBtn.addEventListener('click', function () {
      var open = search.hidden;
      search.hidden = !open;
      searchBtn.setAttribute('aria-expanded', String(open));
      if (open) $('#q').focus();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (header.classList.contains('is-open')) { setMenu(false); menuBtn.focus(); }
      if (!search.hidden) { search.hidden = true; searchBtn.setAttribute('aria-expanded', 'false'); searchBtn.focus(); }
    });
  }

  function urgentHTML(n) {
    return '<div class="urgent" role="status"><span class="urgent__tag">Терміново</span>' +
      '<a href="' + articleUrl(n) + '">' + esc(n.title) + '</a>' +
      '<span class="urgent__time">' + fmtLong(n) + '</span></div>';
  }

  /* ---------- спільні блоки ---------- */
  function cardHTML(n, opts) {
    opts = opts || {};
    var p = n.photo;
    var img = p && p.file ? '<a class="card__img" href="' + articleUrl(n) + '" tabindex="-1" aria-hidden="true"><img' + imgAttrs(p, '(max-width: 600px) 100vw, 400px') + ' alt="' + esc(p.alt) + '" loading="lazy" decoding="async" width="600" height="400"' + pos(p) + '></a>' : '';
    var k = kicker(n);
    var label = k ? (n.rubric ? '<a class="label" href="' + rubricUrl(n.rubric) + '">' + esc(k) + '</a>' : '<span class="label">' + esc(k) + '</span>') : '';
    var extra = '';
    if (n.impact && n.impact.text) {
      extra = '<div class="impact-mini"><strong>' + esc(n.impact.label || 'Що це означає для тебе') + '</strong>' + inline(n.impact.text) + '</div>';
    } else if (n.lead && opts.lead !== false) {
      extra = '<p class="card__lead">' + inline(n.lead) + '</p>';
    }
    var meta = [fmtDay(n), credit(p)].filter(Boolean).join(' · ');
    return '<article class="card">' + img + '<div class="card__body">' + label +
      '<h3 class="card__title"><a href="' + articleUrl(n) + '">' + esc(opts.short && n.cardTitle ? n.cardTitle : n.title) + '</a></h3>' +
      extra + '<span class="card__meta">' + meta + '</span></div></article>';
  }

  function tgStripHTML() {
    return '<section class="tg-strip narrow" aria-label="Telegram"><div class="tg-strip__title">Такі новини – першими в Telegram</div>' +
      '<a class="btn btn--light" href="' + TELEGRAM + '">Підписатися' + ARROW + '</a></section>';
  }

  function notice(target, html) { target.innerHTML = '<div class="notice">' + html + '</div>'; }

  /* ---------- головна ---------- */
  function renderHome(news, raw, data) {
    var hero = news.filter(function (n) { return n.home === 'hero'; })[0] || news[0];
    var heroEl = $('#hero'), cardsEl = $('#cards'), feedEl = $('#feed-list'), numEl = $('#number');

    if (hero) {
      var p = hero.photo;
      var fig = p && p.file ? '<figure class="hero__fig"><img' + imgAttrs(p, '(max-width: 900px) 100vw, 860px') + ' alt="' + esc(p.alt) + '" width="1200" height="800" fetchpriority="high"' + pos(p) + '><figcaption class="photo-credit">' + esc(credit(p)) + '</figcaption></figure>' : '';
      /* Коротка назва джерела – до двокрапки: «AFP / France 24: Київ…» → «AFP / France 24». */
      var src = hero.sources && hero.sources[0] ? ' · Джерело: ' + esc(String(hero.sources[0].title).split(':')[0]) : '';
      heroEl.innerHTML = fig + '<div class="hero__body">' +
        (kicker(hero) ? '<a class="tag" href="' + rubricUrl(hero.rubric) + '">' + esc(kicker(hero)) + '</a>' : '') +
        '<h1 class="hero__title"><a href="' + articleUrl(hero) + '">' + esc(hero.title) + '</a></h1>' +
        (hero.lead ? '<p class="hero__lead">' + inline(hero.lead) + '</p>' : '') +
        '<div class="hero__foot"><a class="btn btn--arrow" href="' + articleUrl(hero) + '">Читати повністю' + ARROW + '</a>' +
        '<span class="meta">' + fmtLong(hero) + src + '</span></div></div>';
    } else {
      heroEl.hidden = true;
    }

    /* Картки «Рішення, які зачеплять тебе» – у тому порядку, як у news.json. */
    var cards = raw.filter(function (n) { return n.home === 'card' && n !== hero; });
    news.forEach(function (n) { if (cards.length < 3 && n !== hero && cards.indexOf(n) === -1) cards.push(n); });
    cardsEl.innerHTML = cards.slice(0, 3).map(function (n) { return cardHTML(n, { short: true, lead: false }); }).join('');

    var feed = news.filter(function (n) { return n !== hero; }).slice(0, 6);
    feedEl.innerHTML = feed.map(function (n) {
      return '<a class="feed__item" href="' + articleUrl(n) + '"><span class="feed__time">' + fmtFeed(n) + '</span>' +
        '<span class="feed__title">' + (isUrgent(n) ? '<span class="urgent-word">Терміново.</span> ' : '') + esc(n.title) + '</span></a>';
    }).join('');
    var note = $('#feed-note');
    if (data.feedNote) note.textContent = data.feedNote; else note.hidden = true;

    var num = data.numberOfDay;
    if (num && num.value) {
      $('#number-value').textContent = num.value;
      $('#number-text').textContent = num.text || '';
      $('#number-note').textContent = num.note || '';
    } else {
      numEl.hidden = true;
    }
  }

  /* ---------- стаття ---------- */
  function setMeta(title, description) {
    document.title = title + ' – Дзеркало влади';
    var pairs = [['meta[name="description"]', description], ['meta[property="og:title"]', title], ['meta[property="og:description"]', description]];
    pairs.forEach(function (p) { var el = $(p[0]); if (el && p[1]) el.setAttribute('content', p[1]); });
  }

  function readMinutes(n) {
    var text = [n.lead].concat((n.body || []).map(function (b) { return typeof b === 'string' ? b : (b.h2 || b.quote || ''); })).join(' ');
    return Math.max(1, Math.round(text.split(/\s+/).filter(Boolean).length / 200));
  }

  function impactHTML(i) {
    return '<div class="impact"><div class="impact__label">' + esc(i.label || 'Що це означає для тебе') + '</div><div class="impact__text">' + inline(i.text) + '</div></div>';
  }

  /* «Перевірка фактів»: вердикт – Правда / Маніпуляція / Неправда (brand/BRAND.md, розділ 7). */
  function verdictHTML(v) {
    return '<div class="verdict"><div class="verdict__label">Вердикт</div>' +
      '<div class="verdict__value">' + esc(v.label) + '</div>' +
      (v.claim ? '<div class="verdict__claim"><strong>Твердження:</strong> ' + inline(v.claim) + '</div>' : '') +
      (v.text ? '<div class="verdict__text">' + inline(v.text) + '</div>' : '') + '</div>';
  }

  function bodyHTML(n) {
    var blocks = Array.isArray(n.body) ? n.body : (n.body ? [n.body] : []);
    var out = [];
    if (n.verdict && n.verdict.label) out.push(verdictHTML(n.verdict));
    blocks.forEach(function (b, i) {
      if (typeof b === 'string') out.push('<p>' + inline(b) + '</p>');
      else if (b && b.h2) out.push('<h2>' + inline(b.h2) + '</h2>');
      else if (b && b.quote) {
        out.push('<blockquote><p>«' + esc(String(b.quote).replace(/^«|»$/g, '')) + '»</p>' + (b.who ? '<footer>' + esc(b.who) + '</footer>' : '') + '</blockquote>');
      }
      if (i === 0 && n.impact && n.impact.text) out.push(impactHTML(n.impact));
    });
    if (!blocks.length && n.impact && n.impact.text) out.push(impactHTML(n.impact));
    if (n.opinion) {
      out.push('<section class="opinion" aria-labelledby="ed-opinion"><div class="opinion__label" id="ed-opinion">Думка редакції</div><div class="opinion__text">' + inline(n.opinion) + '</div></section>');
    }
    var sources = (n.sources || []).filter(function (s) { return s && s.title; });
    out.push('<section class="sources" aria-labelledby="sources-h"><h2 id="sources-h">Джерела</h2>' +
      (sources.length ? '<ol>' + sources.map(function (s) {
        var u = safeUrl(s.url);
        return '<li>' + (u ? '<a href="' + esc(u) + '" target="_blank" rel="noopener">' + esc(s.title) + '</a>' : esc(s.title)) + '</li>';
      }).join('') + '</ol>' : '') +
      '<div class="sources__fix">Знайшли помилку? <a href="about.html#contact">Напишіть редакції</a> – виправимо й позначимо це в тексті.</div></section>');
    return out.join('');
  }

  function renderArticle(news) {
    var main = $('#article');
    var id = new URLSearchParams(location.search).get('id');
    var n = id ? news.filter(function (x) { return x.id === id; })[0] : news.filter(function (x) { return x.home === 'hero'; })[0] || news[0];
    if (!n) {
      document.title = 'Матеріал не знайдено – Дзеркало влади';
      main.innerHTML = '<div class="empty narrow"><h1 class="article__title">Матеріал не знайдено</h1><p>Можливо, посилання застаріло або новину перенесли.</p><a class="btn btn--arrow" href="index.html">На головну' + ARROW + '</a></div>';
      return;
    }
    setMeta(n.title, n.lead || '');
    setActiveNav(n.rubric);
    var p = n.photo, k = kicker(n);
    var shareUrl = encodeURIComponent(location.href);
    var fig = p && p.file ? '<figure class="article__fig"><img' + imgAttrs(p, '(max-width: 800px) 100vw, 760px') + ' alt="' + esc(p.alt) + '" width="1200" height="675" fetchpriority="high"' + pos(p) + '>' +
      '<figcaption>' + (p.caption ? esc(p.caption) + '. ' : '') + esc(credit(p)) + '</figcaption></figure>' : '';

    var related = news.filter(function (x) { return x !== n && n.rubric && x.rubric === n.rubric; });
    var hasPhoto = function (x) { return !!(x.photo && x.photo.file); };
    news.filter(hasPhoto).concat(news).forEach(function (x) { if (x !== n && related.indexOf(x) === -1) related.push(x); });
    related = related.slice(0, 3);

    main.innerHTML = '<article class="article">' +
      (k ? '<div>' + (isUrgent(n) ? '<span class="urgent__tag">Терміново</span> ' : '') + (n.rubric ? '<a class="label" href="' + rubricUrl(n.rubric) + '">' + esc(k) + '</a>' : '<span class="label">' + esc(k) + '</span>') + '</div>'
         : (isUrgent(n) ? '<div><span class="urgent__tag">Терміново</span></div>' : '')) +
      '<h1 class="article__title">' + esc(n.title) + '</h1>' +
      (n.lead ? '<p class="article__lead">' + inline(n.lead) + '</p>' : '') +
      '<div class="article__bar"><div class="meta">' + (n.author ? '<strong>' + esc(n.author) + '</strong> · ' : '') + fmtLong(n) + ' · ' + readMinutes(n) + ' хв читання</div>' +
      '<div class="share">' +
      '<a class="btn-outline" href="https://t.me/share/url?url=' + shareUrl + '&amp;text=' + encodeURIComponent(n.title) + '" target="_blank" rel="noopener">Telegram</a>' +
      '<a class="btn-outline" href="https://www.facebook.com/sharer/sharer.php?u=' + shareUrl + '" target="_blank" rel="noopener">Facebook</a>' +
      '<button type="button" class="btn-outline" id="copy-link">Скопіювати посилання</button></div></div>' +
      fig +
      '<div class="prose">' + bodyHTML(n) + '</div>' +
      '</article>' +
      tgStripHTML() +
      (related.length ? '<section class="related" aria-labelledby="related-h"><div class="section-head" style="margin-bottom:24px"><span class="label">Більше новин</span><h2 id="related-h">Читайте також</h2></div>' +
        '<div class="cards">' + related.map(function (x) { return cardHTML(x, { short: true }); }).join('') + '</div></section>' : '');

    var copy = $('#copy-link');
    copy.addEventListener('click', function () {
      function done() { copy.textContent = 'Посилання скопійовано'; setTimeout(function () { copy.textContent = 'Скопіювати посилання'; }, 2500); }
      if (navigator.clipboard) navigator.clipboard.writeText(location.href).then(done, function () { prompt('Скопіюйте посилання:', location.href); });
      else prompt('Скопіюйте посилання:', location.href);
    });
  }

  /* ---------- сторінка рубрики ---------- */
  function renderRubric(news) {
    var root = $('#rubric');

    function draw() {
      var params = new URLSearchParams(location.search);
      var slug = params.get('r') || '';
      var q = (params.get('q') || '').trim();
      var name = rubricName(slug);
      if (slug && !name) slug = '';

      var list = news.filter(function (n) { return !slug || n.rubric === slug; });
      if (q) {
        var ql = q.toLowerCase();
        list = list.filter(function (n) { return [n.title, n.cardTitle, n.lead, kicker(n)].join(' ').toLowerCase().indexOf(ql) !== -1; });
      }
      var title = q ? 'Пошук: «' + q + '»' : (name || 'Усі новини');
      document.title = title + ' – Дзеркало влади';
      setActiveNav(slug);
      var input = $('#q'); if (input && q) input.value = q;

      var chips = '<a class="chip" href="rubric.html"' + (!slug ? ' aria-current="page"' : '') + '>Усі</a>' +
        RUBRICS.map(function (r) {
          return '<a class="chip" href="' + rubricUrl(r.slug) + '"' + (r.slug === slug ? ' aria-current="page"' : '') + '>' + esc(r.name) + '</a>';
        }).join('');

      root.innerHTML = '<div class="rubric-head"><span class="label">' + (name && !q ? 'Рубрика' : 'Дзеркало влади') + '</span>' +
        '<h1>' + esc(title) + '</h1>' +
        '<nav class="chips" aria-label="Фільтр за рубрикою">' + chips + '</nav>' +
        '<p class="meta" aria-live="polite">' + list.length + ' ' + plural(list.length, 'матеріал', 'матеріали', 'матеріалів') + '</p></div>' +
        (list.length ? '<div class="grid">' + list.map(function (n) { return cardHTML(n, { short: true }); }).join('') + '</div>'
          : '<div class="empty"><h2>' + (q ? 'Нічого не знайшли' : 'Тут поки немає матеріалів') + '</h2><p>' + (q ? 'Спробуйте інше слово або перегляньте всі новини.' : 'Щойно в цій рубриці зʼявляться новини, вони будуть тут.') + '</p>' +
            '<a class="btn btn--arrow" href="rubric.html">Усі новини' + ARROW + '</a></div>');
    }

    /* Фільтр без перезавантаження сторінки. */
    root.addEventListener('click', function (e) {
      var a = e.target.closest('a.chip');
      if (!a || e.ctrlKey || e.metaKey || e.shiftKey) return;
      e.preventDefault();
      history.pushState(null, '', a.getAttribute('href'));
      draw();
    });
    window.addEventListener('popstate', draw);
    draw();
  }

  /* ---------- запуск ---------- */
  /* Поки дані не підвантажились, вміст сторінки прихований (body.is-loading) – так блоки не «стрибають». */
  function loaded() { document.body.classList.remove('is-loading'); }

  function init() {
    var page = document.body.getAttribute('data-page');
    $('#site-header').innerHTML = headerHTML();
    $('#site-footer').innerHTML = footerHTML();
    initHeader();
    setTimeout(loaded, 4000); // запобіжник, якщо дані вантажаться надто довго

    fetch('data/news.json')
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        var raw = (data.news || []).filter(function (n) { return n && n.id && n.title; });
        raw.forEach(function (n) { n._d = parseDate(n.date); });
        var news = raw.slice().sort(function (a, b) { return b._d.d - a._d.d; });

        var urgent = news.filter(isUrgent)[0];
        if (urgent) $('#main').insertAdjacentHTML('afterbegin', urgentHTML(urgent));

        if (page === 'home') renderHome(news, raw, data);
        else if (page === 'article') renderArticle(news);
        else if (page === 'rubric') renderRubric(news);
      })
      .then(loaded, function (e) { loaded(); throw e; })
      .catch(function () {
        var target = $('#hero') || $('#article') || $('#rubric');
        if (target) notice(target, '<strong>Не вдалося завантажити новини.</strong> Якщо ви відкрили файл подвійним клацанням, запустіть сайт через локальний сервер (інструкція – у файлі САЙТ.md).');
      });
  }

  init();
})();

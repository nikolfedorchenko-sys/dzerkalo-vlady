// Cloudflare Worker «Дзеркало влади»:
// 1) будильник автопостингу – щогодини запускає робота в GitHub; робот сам перевіряє,
//    чи зараз година публікації (autopost/config.yaml, рядок slots);
// 2) бот «Надіслати новину» – вітається, пересилає редакції (ADMIN_CHAT) усе, що надіслали люди, і дякує;
// 3) кнопки «Опублікувати» / «Відхилити» під чернетками, які робот надсилає власнику (бот автопостингу):
//    схвалення зберігаються на добу в KV (APPROVALS), і робот у GitHub публікує всі схвалені чернетки.
export default {
  async scheduled(event, env, ctx) {
    // О :02 – звичайний запуск; о :17, :32, :47 – тільки черга Telegram (пости з інтервалом 10–20 хв)
    if (event.cron.startsWith("2 ")) {
      ctx.waitUntil(dispatch(env, { action: "За розкладом" }));
    } else {
      ctx.waitUntil(queueTick(env));
    }
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    // Одноразове підключення бота: відкрити /setup у браузері
    // Підключення ботів: відкрити /setup у браузері (робиться саме після кожного розгортання)
    if (request.method === "GET" && url.pathname === "/setup") {
      const res = await tg(env, "setWebhook", {
        url: `${url.origin}/telegram`,
        secret_token: await hookSecret(env),
        allowed_updates: ["message"],
      });
      const lines = [res.ok ? "Бот «Надіслати новину» підключено" : `Бот «Надіслати новину»: помилка ${res.description}`];
      if (env.AUTOPOST_BOT_TOKEN) {
        const res2 = await tg(env, "setWebhook", {
          url: `${url.origin}/autopost`,
          secret_token: await hookSecret(env, env.AUTOPOST_BOT_TOKEN),
          allowed_updates: ["callback_query"],
        }, env.AUTOPOST_BOT_TOKEN);
        lines.push(res2.ok ? "Кнопки бота автопостингу підключено" : `Бот автопостингу: помилка ${res2.description}`);
      } else {
        lines.push("Бот автопостингу: немає секрету AUTOPOST_BOT_TOKEN");
      }
      return new Response(lines.join("\n"), { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    if (request.method === "POST" && url.pathname === "/autopost") {
      if (!env.AUTOPOST_BOT_TOKEN ||
          request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== (await hookSecret(env, env.AUTOPOST_BOT_TOKEN))) {
        return new Response("forbidden", { status: 403 });
      }
      const update = await request.json();
      if (update.callback_query) await onButton(env, update.callback_query);
      return new Response("ok");
    }
    // Діагностика: який бот підключено і чи доходять до нього повідомлення (токен не показується)
    if (request.method === "GET" && url.pathname === "/status") {
      const me = await tg(env, "getMe", {});
      const hook = await tg(env, "getWebhookInfo", {});
      const h = hook.result || {};
      const info = {
        bot: me.result ? `@${me.result.username}` : me.description,
        webhook: h.url ? h.url.replace(/^https:\/\/[^/]+/, "…") : "не підключено",
        pending: h.pending_update_count,
        last_error: h.last_error_message || "немає",
        last_queue_tick: JSON.parse((await env.APPROVALS.get("last_queue_tick")) || "null"),
        last_dispatch_error: (await env.APPROVALS.get("last_dispatch_error")) || "немає",
      };
      return new Response(JSON.stringify(info, null, 1), { headers: { "content-type": "application/json; charset=utf-8" } });
    }
    if (request.method === "POST" && url.pathname === "/telegram") {
      if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== (await hookSecret(env))) {
        return new Response("forbidden", { status: 403 });
      }
      const update = await request.json();
      await onMessage(env, update.message);
      return new Response("ok");
    }
    return new Response("Дзеркало влади", { headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};

const WELCOME =
  "Вітаємо в «Дзеркалі влади».\n\n" +
  "Надішліть сюди новину, фото, відео чи документ про рішення влади – від Київради до Верховної Ради. " +
  "Можна анонімно: ми не розкриваємо джерел.\n\n" +
  "Кожне повідомлення читає редакція. Перш ніж публікувати, ми перевіряємо факти.";
const THANKS = "Дякуємо! Редакція отримала ваше повідомлення. Якщо будуть питання – напишемо сюди ж.";

async function onMessage(env, msg) {
  if (!msg || !msg.chat || msg.chat.type !== "private") return;
  if (msg.text && msg.text.startsWith("/start")) {
    await tg(env, "sendMessage", { chat_id: msg.chat.id, text: WELCOME });
    return;
  }
  const who = [msg.from?.first_name, msg.from?.last_name].filter(Boolean).join(" ");
  const nick = msg.from?.username ? ` @${msg.from.username}` : "";
  await tg(env, "sendMessage", { chat_id: env.ADMIN_CHAT, text: `Новина від читача: ${who}${nick} (id ${msg.from?.id})` });
  await tg(env, "forwardMessage", { chat_id: env.ADMIN_CHAT, from_chat_id: msg.chat.id, message_id: msg.message_id });
  await tg(env, "sendMessage", { chat_id: msg.chat.id, text: THANKS });
}

// Кнопка під чернеткою: «pub:<ключ>» – опублікувати, «rej:<ключ>» – відхилити. Натискати може тільки власник.
async function onButton(env, q) {
  const token = env.AUTOPOST_BOT_TOKEN;
  const answer = (text) => tg(env, "answerCallbackQuery", { callback_query_id: q.id, text }, token);
  if (String(q.from?.id) !== String(env.ADMIN_CHAT)) return answer("Недостатньо прав");
  const [act, key] = String(q.data || "").split(":");
  const mark = (text) =>
    tg(env, "editMessageReplyMarkup", {
      chat_id: q.message.chat.id,
      message_id: q.message.message_id,
      reply_markup: { inline_keyboard: [[{ text, callback_data: "noop" }]] },
    }, token);
  if (act === "rej" && key) {
    await env.APPROVALS.delete(`ok:${key}`);
    await mark("❌ Відхилено");
    return answer("Відхилено");
  }
  if (act === "pub" && key) {
    await env.APPROVALS.put(`ok:${key}`, "1", { expirationTtl: 86400 });
    // Передаємо всі схвалення за добу: якщо GitHub скасує чергу, наступний запуск однаково опублікує всі
    const list = await env.APPROVALS.list({ prefix: "ok:" });
    const keys = list.keys.map((k) => k.name.slice(3)).join(",");
    const ok = await dispatch(env, { action: "Опублікувати чернетку", drafts: keys });
    if (!ok) return answer("Не вдалося запустити робота – спробуйте ще раз");
    await mark("⏳ Публікується – за 2–5 хвилин прийде звіт");
    return answer("Публікую");
  }
  return answer("");
}

async function tg(env, method, body, token = env.NEWS_BOT_TOKEN) {
  const res = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

// Секрет для вебхука виводимо з токена бота – окремо нічого зберігати не треба
async function hookSecret(env, token = env.NEWS_BOT_TOKEN) {
  const data = new TextEncoder().encode(`dv-news-${token}`);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 48);
}

// Черга Telegram: запускаємо робота, лише коли він зараз не працює. Інакше GitHub скасував би запуск,
// що чекає в черзі (наприклад, публікацію схваленої чернетки), а пости з черги підуть наступного разу.
async function queueTick(env) {
  const note = (result) => env.APPROVALS.put("last_queue_tick", JSON.stringify({ at: new Date().toISOString(), result }));
  try {
    await queueTickInner(env, note);
  } catch (e) {
    await note(`помилка: ${e}`);
  }
}

async function queueTickInner(env, note) {
  const res = await fetch(`https://api.github.com/repos/${env.REPO}/actions/workflows/autopost.yml/runs?per_page=5`, {
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "dv-autopost-budylnyk",
    },
  });
  if (res.ok) {
    const { workflow_runs = [] } = await res.json();
    const busy = workflow_runs.filter((r) => r.status !== "completed");
    if (busy.length) return note(`пропущено: робот працює (${busy.map((r) => r.status).join(", ")})`);
  } else {
    await note(`GitHub (список запусків) відповів ${res.status}`);
  }
  const ok = await dispatch(env, { action: "Черга Telegram" });
  await note(ok ? "запущено" : "GitHub не прийняв запуск");
}

async function dispatch(env, inputs) {
  const url = `https://api.github.com/repos/${env.REPO}/actions/workflows/autopost.yml/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "dv-autopost-budylnyk",
    },
    body: JSON.stringify({ ref: "main", inputs }),
  });
  if (!res.ok) {
    const text = await res.text();
    console.log(`GitHub відповів ${res.status}: ${text}`);
    await env.APPROVALS.put("last_dispatch_error", `${new Date().toISOString()} ${res.status}: ${text.slice(0, 300)}`);
  }
  return res.ok;
}

// Cloudflare Worker «Дзеркало влади»:
// 1) будильник автопостингу – щогодини запускає робота в GitHub; робот сам перевіряє,
//    чи зараз година публікації (autopost/config.yaml, рядок slots);
// 2) бот «Надіслати новину» – вітається, пересилає редакції (ADMIN_CHAT) усе, що надіслали люди, і дякує.
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(wake(env));
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    // Одноразове підключення бота: відкрити /setup у браузері
    if (request.method === "GET" && url.pathname === "/setup") {
      const res = await tg(env, "setWebhook", {
        url: `${url.origin}/telegram`,
        secret_token: await hookSecret(env),
        allowed_updates: ["message"],
      });
      return new Response(res.ok ? "Бот підключено" : `Помилка: ${res.description}`, {
        headers: { "content-type": "text/plain; charset=utf-8" },
      });
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
  const fromAdmin = String(msg.chat.id) === String(env.ADMIN_CHAT);
  if (fromAdmin) return; // власні повідомлення редакції не пересилаємо
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

async function tg(env, method, body) {
  const res = await fetch(`https://api.telegram.org/bot${env.NEWS_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

// Секрет для вебхука виводимо з токена бота – окремо нічого зберігати не треба
async function hookSecret(env) {
  const data = new TextEncoder().encode(`dv-news-${env.NEWS_BOT_TOKEN}`);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 48);
}

async function wake(env) {
  const url = `https://api.github.com/repos/${env.REPO}/actions/workflows/autopost.yml/dispatches`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "dv-autopost-budylnyk",
    },
    body: JSON.stringify({ ref: "main", inputs: { action: "За розкладом" } }),
  });
  if (!res.ok) console.log(`GitHub відповів ${res.status}: ${await res.text()}`);
}

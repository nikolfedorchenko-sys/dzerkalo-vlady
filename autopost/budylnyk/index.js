// Запасний будильник автопостингу «Дзеркало влади».
// Cloudflare щогодини запускає робота в GitHub; робот сам перевіряє, чи зараз година публікації
// (години – в autopost/config.yaml, рядок slots).
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(wake(env));
  },
};

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

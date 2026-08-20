import { getItem, searchMercadoLibre, sessionInfo } from "./search.js";

const BRIDGE = "http://127.0.0.1:18765";
const ALARM = "ml-bridge-poll";

let looping = false;

chrome.runtime.onInstalled.addListener(() => start());
chrome.runtime.onStartup.addListener(() => start());
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) start();
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handleMessage(msg).then(sendResponse).catch((err) => {
    sendResponse({ ok: false, error: String(err.message || err) });
  });
  return true;
});

start();

async function start() {
  await chrome.alarms.create(ALARM, { periodInMinutes: 0.4 });
  if (looping) return;
  looping = true;
  pollLoop().finally(() => {
    looping = false;
  });
}

async function handleMessage(msg) {
  if (msg?.type === "status") {
    const session = await sessionInfo(msg.site || "MLA");
    const bridge = await bridgeStatus();
    return { ok: true, session, bridge };
  }
  if (msg?.type === "pair") {
    return pair();
  }
  if (msg?.type === "search") {
    const data = await searchMercadoLibre(msg);
    return { ok: true, data };
  }
  if (msg?.type === "item") {
    const data = await getItem(msg);
    return { ok: true, data };
  }
  return { ok: false, error: "unknown message" };
}

async function pollLoop() {
  for (let i = 0; i < 200; i += 1) {
    try {
      const token = await getToken();
      const res = await fetch(`${BRIDGE}/v1/next?wait=20`, {
        headers: tokenHeaders(token),
      });
      if (res.status === 204) continue;
      if (res.status === 401 || res.status === 403) {
        await pair();
        continue;
      }
      if (!res.ok) {
        await sleep(1500);
        continue;
      }
      const job = await res.json();
      const result = await runJob(job);
      await fetch(`${BRIDGE}/v1/result`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...tokenHeaders(await getToken()),
        },
        body: JSON.stringify(result),
      });
    } catch {
      await sleep(2000);
    }
  }
}

async function runJob(job) {
  const id = job.id;
  try {
    if (job.action === "search") {
      const data = await searchMercadoLibre(job);
      return { id, ok: true, data };
    }
    if (job.action === "search_many") {
      const queries = Array.isArray(job.queries) ? job.queries : [];
      const searches = [];
      for (const q of queries.slice(0, 20)) {
        const data = await searchMercadoLibre({
          query: q.query || q,
          site: q.site || job.site,
          limit: q.limit || job.limit || 8,
          condition: q.condition || job.condition || "new",
          sort: q.sort || job.sort || "price_asc",
        });
        searches.push({ id: q.id || q.query, ...data });
      }
      return { id, ok: true, data: { searches } };
    }
    if (job.action === "item") {
      const data = await getItem(job);
      return { id, ok: true, data };
    }
    if (job.action === "status") {
      const session = await sessionInfo(job.site || "MLA");
      return { id, ok: true, data: { session, extension: "ml-price-bridge/1.0.0" } };
    }
    return { id, ok: false, error: `unknown action: ${job.action}` };
  } catch (err) {
    return { id, ok: false, error: String(err.message || err) };
  }
}

async function pair() {
  try {
    const res = await fetch(`${BRIDGE}/v1/pair`, { method: "POST" });
    if (!res.ok) return { ok: false, error: `pair failed: HTTP ${res.status}` };
    const data = await res.json();
    if (data.token) await chrome.storage.local.set({ token: data.token });
    return { ok: true, paired: true };
  } catch (err) {
    return { ok: false, error: "Grok bridge is not running. Open a Grok session first." };
  }
}

async function bridgeStatus() {
  try {
    const res = await fetch(`${BRIDGE}/v1/status`, {
      headers: tokenHeaders(await getToken()),
    });
    if (!res.ok) return { connected: false };
    const data = await res.json();
    return { connected: true, ...data };
  } catch {
    return { connected: false };
  }
}

async function getToken() {
  const stored = await chrome.storage.local.get("token");
  return stored.token || "";
}

function tokenHeaders(token) {
  return token ? { "X-Bridge-Token": token } : {};
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

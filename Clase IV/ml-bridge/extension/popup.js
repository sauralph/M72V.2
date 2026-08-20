const mlState = document.getElementById("ml-state");
const bridgeState = document.getElementById("bridge-state");
const out = document.getElementById("out");

document.getElementById("open-ml").addEventListener("click", () => {
  chrome.tabs.create({ url: "https://www.mercadolibre.com.ar/" });
});

document.getElementById("reconnect").addEventListener("click", async () => {
  const res = await chrome.runtime.sendMessage({ type: "pair" });
  renderStatus();
  show(res.ok ? "Paired with Grok bridge." : res.error || "Could not pair.");
});

document.getElementById("search").addEventListener("click", runSearch);
document.getElementById("query").addEventListener("keydown", (event) => {
  if (event.key === "Enter") runSearch();
});

renderStatus();

async function renderStatus() {
  const res = await chrome.runtime.sendMessage({ type: "status", site: "MLA" });
  if (!res?.ok) {
    setState(mlState, "error", "unavailable");
    setState(bridgeState, "bad", "extension error");
    return;
  }
  if (res.session.loggedIn) setState(mlState, "ok", "logged in");
  else setState(mlState, "bad", "not logged in");

  if (res.bridge.connected) setState(bridgeState, "ok", "connected");
  else setState(bridgeState, "wait", "Grok not running");
}

async function runSearch() {
  const query = document.getElementById("query").value.trim();
  if (!query) return;
  show("Searching…");
  const res = await chrome.runtime.sendMessage({
    type: "search",
    query,
    site: "MLA",
    limit: 8,
    condition: "new",
    sort: "price_asc",
  });
  if (!res?.ok) {
    show(res?.error || "Search failed");
    return;
  }
  const rows = (res.data.results || []).map((item) => {
    const price = item.price != null ? `${item.currency || ""} ${formatPrice(item.price)}`.trim() : "n/a";
    return `${price}  ${item.title}`;
  });
  const header = `${res.data.results.length} results via ${res.data.source}` +
    (res.data.warning ? `\n${res.data.warning}` : "");
  show([header, ...rows].join("\n"));
}

function setState(el, kind, label) {
  el.className = kind;
  el.textContent = label;
}

function show(text) {
  out.hidden = false;
  out.textContent = text;
}

function formatPrice(n) {
  return Number(n).toLocaleString("es-AR");
}

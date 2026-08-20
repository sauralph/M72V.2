import { SITES } from "./sites.js";

const LOGIN_COOKIE_HINTS = ["ssid", "nicks", "orguserid", "sid", "ss"];

export async function sessionInfo(siteId = "MLA") {
  const site = SITES[siteId] || SITES.MLA;
  const cookies = [];
  for (const domain of site.cookieDomains) {
    const found = await chrome.cookies.getAll({ domain });
    cookies.push(...found);
  }
  const names = new Set(cookies.map((c) => c.name.toLowerCase()));
  const loggedIn = LOGIN_COOKIE_HINTS.some((n) => names.has(n));
  return {
    site: siteId,
    host: site.host,
    loggedIn,
    cookieCount: cookies.length,
  };
}

export async function searchMercadoLibre(job) {
  const siteId = (job.site || "MLA").toUpperCase();
  const site = SITES[siteId] || SITES.MLA;
  const limit = clamp(job.limit || 15, 1, 50);
  const condition = job.condition || "new";
  const sort = job.sort || "relevance";
  const query = String(job.query || "").trim();
  if (!query) throw new Error("query is required");

  const session = await sessionInfo(siteId);
  const errors = [];

  try {
    const apiItems = await searchApi(siteId, query, limit, condition, sort);
    if (apiItems.length) {
      return {
        source: "api",
        site: siteId,
        query,
        session,
        results: apiItems.slice(0, limit),
      };
    }
  } catch (err) {
    errors.push(`api: ${err.message || err}`);
  }

  try {
    const htmlItems = await searchListado(site, siteId, query, limit, condition, sort);
    if (htmlItems.length) {
      return {
        source: "listado",
        site: siteId,
        query,
        session,
        results: htmlItems.slice(0, limit),
      };
    }
  } catch (err) {
    errors.push(`listado: ${err.message || err}`);
  }

  try {
    const tabItems = await searchViaTab(site, query, limit, condition, sort);
    if (tabItems.length) {
      return {
        source: "tab",
        site: siteId,
        query,
        session,
        results: tabItems.slice(0, limit),
      };
    }
  } catch (err) {
    errors.push(`tab: ${err.message || err}`);
  }

  return {
    source: "empty",
    site: siteId,
    query,
    session,
    results: [],
    warning: session.loggedIn
      ? `Logged in, but no listings were parsed. ${errors.join(" | ") || "Try a simpler query."}`
      : "No listings parsed. Log into Mercado Libre in this browser, then retry.",
  };
}

export async function getItem(job) {
  const id = String(job.id || job.item_id || "").trim();
  if (!id) throw new Error("id is required");
  const url = `https://api.mercadolibre.com/items/${encodeURIComponent(id)}`;
  const res = await fetch(url, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    throw new Error(`item ${id} failed: HTTP ${res.status}`);
  }
  const data = await res.json();
  return normalizeApiItem(data);
}

async function searchApi(siteId, query, limit, condition, sort) {
  const params = new URLSearchParams({
    q: query,
    limit: String(limit),
  });
  if (condition === "new") params.set("condition", "new");
  if (condition === "used") params.set("condition", "used");
  if (sort === "price_asc") params.set("sort", "price_asc");
  if (sort === "price_desc") params.set("sort", "price_desc");

  const url = `https://api.mercadolibre.com/sites/${siteId}/search?${params}`;
  try {
    const res = await fetch(url, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return [];
    const data = await res.json();
    const results = Array.isArray(data.results) ? data.results : [];
    return results.map(normalizeApiItem).filter((x) => x.id);
  } catch {
    return [];
  }
}

async function searchListado(site, siteId, query, limit, condition, sort) {
  const slug = slugify(query);
  const filters = [];
  if (condition === "new") filters.push("ITEM*CONDITION_2230284");
  if (condition === "used") filters.push("ITEM*CONDITION_2230581");
  if (sort === "price_asc") filters.push("OrderId_PRICE");
  if (sort === "price_desc") filters.push("OrderId_PRICE*DESC");
  const suffix = filters.length ? `_${filters.join("_")}` : "";
  const url = `${site.listado}/${encodeURIComponent(slug)}${suffix}`;

  const items = await fetchListado(url, site.currency);
  if (items.length || !suffix) return items.slice(0, Math.max(limit, 20));
  const plain = await fetchListado(`${site.listado}/${encodeURIComponent(slug)}`, site.currency);
  return plain.slice(0, Math.max(limit, 20));
}

function listadoUrl(site, query, condition, sort) {
  const slug = slugify(query);
  const filters = [];
  if (condition === "new") filters.push("ITEM*CONDITION_2230284");
  if (condition === "used") filters.push("ITEM*CONDITION_2230581");
  if (sort === "price_asc") filters.push("OrderId_PRICE");
  if (sort === "price_desc") filters.push("OrderId_PRICE*DESC");
  const suffix = filters.length ? `_${filters.join("_")}` : "";
  return `${site.listado}/${encodeURIComponent(slug)}${suffix}`;
}

async function searchViaTab(site, query, limit, condition, sort) {
  const { id: tabId, owned } = await ensureMlTab(site);
  try {
    const info = await waitForMlTab(tabId, 25000);
    if (isErrorUrl(info.url)) {
      throw new Error(`Mercado Libre tab failed to load (${info.url || "error page"}). Keep mercadolibre.com.ar open and retry.`);
    }

    const [{ result: apiResult } = {}] = await chrome.scripting.executeScript({
      target: { tabId },
      func: pageApiSearch,
      args: [query, limit, condition, sort],
    });
    const apiItems = (apiResult?.results || []).map(normalizeApiItem).filter((item) => item.id);
    if (apiItems.length) return apiItems.slice(0, Math.max(limit, 20));

    const searchUrl = `${site.listado}/${slugify(query)}`;
    await chrome.tabs.update(tabId, { url: searchUrl });
    const after = await waitForMlTab(tabId, 25000);
    if (isErrorUrl(after.url)) {
      throw new Error(`listado tab error: ${after.url}`);
    }
    const [{ result: scraped } = {}] = await chrome.scripting.executeScript({
      target: { tabId },
      func: scrapeListadoPage,
    });
    return (scraped || []).slice(0, Math.max(limit, 20));
  } finally {
    if (owned && tabId) chrome.tabs.remove(tabId).catch(() => {});
  }
}

async function ensureMlTab(site) {
  const matches = await chrome.tabs.query({
    url: [
      `https://${site.host}/*`,
      "https://*.mercadolibre.com.ar/*",
      "https://*.mercadolibre.com/*",
      `${site.listado}/*`,
    ],
  });
  const existing = matches.find((tab) => tab.id && !isErrorUrl(tab.url));
  if (existing) return { id: existing.id, owned: false };

  const tab = await chrome.tabs.create({
    url: `https://${site.host}/`,
    active: true,
  });
  return { id: tab.id, owned: true };
}

function isErrorUrl(url) {
  const value = String(url || "");
  return !value || value.startsWith("chrome-error://") || value.startsWith("chrome://") || value.startsWith("about:");
}

async function waitForMlTab(tabId, timeoutMs) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete" && tab.url && !isErrorUrl(tab.url)) {
      await sleep(600);
      return tab;
    }
    if (tab.status === "complete" && isErrorUrl(tab.url) && Date.now() - started > 4000) {
      return tab;
    }
    await sleep(250);
  }
  const tab = await chrome.tabs.get(tabId);
  return tab;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pageApiSearch(query, limit, condition, sort) {
  const params = new URLSearchParams({ q: query, limit: String(limit || 15) });
  if (condition === "new") params.set("condition", "new");
  if (condition === "used") params.set("condition", "used");
  if (sort === "price_asc") params.set("sort", "price_asc");
  if (sort === "price_desc") params.set("sort", "price_desc");
  const siteGuess = location.hostname.includes("mercadolivre")
    ? "MLB"
    : location.hostname.endsWith(".mx")
      ? "MLM"
      : location.hostname.endsWith(".cl")
        ? "MLC"
        : location.hostname.endsWith(".co")
          ? "MCO"
          : location.hostname.endsWith(".uy")
            ? "MLU"
            : "MLA";
  const url = `https://api.mercadolibre.com/sites/${siteGuess}/search?${params.toString()}`;
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) return { ok: false, status: res.status, results: [] };
  const data = await res.json();
  return { ok: true, results: Array.isArray(data.results) ? data.results : [] };
}

function waitForTab(tabId, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(new Error("tab load timeout"));
    }, timeoutMs);

    function onUpdated(id, info) {
      if (id === tabId && info.status === "complete") {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(onUpdated);
        setTimeout(resolve, 800);
      }
    }

    chrome.tabs.get(tabId, (tab) => {
      if (chrome.runtime.lastError) {
        clearTimeout(timer);
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (tab.status === "complete") {
        clearTimeout(timer);
        setTimeout(resolve, 800);
        return;
      }
      chrome.tabs.onUpdated.addListener(onUpdated);
    });
  });
}

function scrapeListadoPage() {
  const text = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const parsePrice = (fraction, cents) => {
    const whole = String(fraction || "").replace(/[^\d]/g, "");
    if (!whole) return null;
    const frac = String(cents || "").replace(/[^\d]/g, "");
    return frac ? Number(`${whole}.${frac}`) : Number(whole);
  };
  const extractId = (value) => {
    const m = String(value || "").match(/\b(MLA|MLM|MLB|MLC|MCO|MLU)\d{6,}\b/i);
    return m ? m[0].toUpperCase() : null;
  };

  const cards = [
    ...document.querySelectorAll(
      "li.ui-search-layout__item, div.ui-search-result, div.poly-card, ol.ui-search-layout > li, .ui-search-layout__item"
    ),
  ];
  const items = [];
  for (const card of cards) {
    const link =
      card.querySelector("a.poly-component__title, a.ui-search-link, a.ui-search-item__group__element, a[href*='/p/']") ||
      card.querySelector("a[href*='mercadolibre']");
    const titleEl = card.querySelector(
      "h2, h3, a.poly-component__title, .ui-search-item__title, .poly-component__title"
    );
    const frac = card.querySelector(".andes-money-amount__fraction");
    const cents = card.querySelector(".andes-money-amount__cents");
    const href = link?.href || link?.getAttribute("href");
    const title = text(titleEl?.textContent || link?.textContent);
    const price = parsePrice(frac?.textContent, cents?.textContent);
    if (!title || !price || !href) continue;
    items.push({
      id: extractId(href),
      title,
      price,
      currency: "ARS",
      permalink: href.split("#")[0],
      thumbnail: card.querySelector("img")?.src || null,
      condition: null,
      seller: text(card.querySelector(".poly-component__seller")?.textContent) || null,
      shipping: text(card.querySelector(".poly-component__shipping, .ui-search-item__shipping")?.textContent) || null,
    });
  }
  return items;
}

async function fetchListado(url, currency) {
  try {
    const res = await fetch(url, {
      credentials: "include",
      headers: {
        Accept: "text/html,application/xhtml+xml",
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
      },
      redirect: "follow",
    });
    if (!res.ok) return [];
    const html = await res.text();
    if (/account-verification/i.test(res.url) || /gz\/account-verification/i.test(html.slice(0, 4000))) {
      return [];
    }
    return parseListadoHtml(html, currency);
  } catch (err) {
    throw new Error(`listado fetch failed: ${err.message || err} (${url})`);
  }
}

function parseListadoHtml(html, fallbackCurrency) {
  const fromLd = parseJsonLd(html, fallbackCurrency);
  if (fromLd.length) return dedupe(fromLd);

  const fromState = parseEmbeddedJson(html, fallbackCurrency);
  if (fromState.length) return dedupe(fromState);

  const fromDom = parseDomCards(html, fallbackCurrency);
  return dedupe(fromDom);
}

function parseJsonLd(html, fallbackCurrency) {
  const items = [];
  const re = /<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html))) {
    try {
      const data = JSON.parse(m[1]);
      const nodes = Array.isArray(data) ? data : [data];
      for (const node of nodes) collectLd(node, items, fallbackCurrency);
    } catch {
      /* ignore broken ld+json */
    }
  }
  return items;
}

function collectLd(node, items, fallbackCurrency) {
  if (!node || typeof node !== "object") return;
  if (node["@type"] === "ItemList" && Array.isArray(node.itemListElement)) {
    for (const el of node.itemListElement) {
      collectLd(el.item || el, items, fallbackCurrency);
    }
  }
  if (node["@type"] === "Product" || node.offers) {
    const offer = Array.isArray(node.offers) ? node.offers[0] : node.offers || {};
    const price = toNumber(offer.price ?? offer.lowPrice);
    if (node.name && price) {
      items.push({
        id: extractId(node.sku || node.url || ""),
        title: text(node.name),
        price,
        currency: offer.priceCurrency || fallbackCurrency,
        permalink: node.url || null,
        thumbnail: (node.image && (node.image.url || node.image)) || null,
        condition: null,
        seller: null,
        shipping: null,
      });
    }
  }
}

function parseEmbeddedJson(html, fallbackCurrency) {
  const items = [];
  const candidates = [];
  const next = html.match(/<script[^>]*id=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/i);
  if (next) candidates.push(next[1]);
  const pre = html.match(/__PRELOADED_STATE__\s*=\s*(\{[\s\S]*?\});/);
  if (pre) candidates.push(pre[1]);

  for (const raw of candidates) {
    try {
      walkForListings(JSON.parse(raw), items, fallbackCurrency, 0);
    } catch {
      /* ignore */
    }
  }

  // Last resort: find "results":[ ... ] blobs with permalinks.
  const blob = html.match(/"results"\s*:\s*(\[[\s\S]{200,200000}?\])/);
  if (blob && !items.length) {
    try {
      const arr = JSON.parse(blob[1]);
      if (Array.isArray(arr)) {
        for (const row of arr) {
          const n = normalizeLoose(row, fallbackCurrency);
          if (n) items.push(n);
        }
      }
    } catch {
      /* ignore */
    }
  }
  return items;
}

function walkForListings(node, items, fallbackCurrency, depth) {
  if (!node || depth > 10) return;
  if (Array.isArray(node)) {
    if (node.length && node[0] && (node[0].permalink || node[0].price || node[0].id)) {
      for (const row of node) {
        const n = normalizeLoose(row, fallbackCurrency);
        if (n) items.push(n);
      }
      return;
    }
    for (const child of node.slice(0, 40)) walkForListings(child, items, fallbackCurrency, depth + 1);
    return;
  }
  if (typeof node !== "object") return;
  if (Array.isArray(node.results)) {
    walkForListings(node.results, items, fallbackCurrency, depth + 1);
    return;
  }
  for (const key of Object.keys(node).slice(0, 40)) {
    if (items.length > 60) return;
    walkForListings(node[key], items, fallbackCurrency, depth + 1);
  }
}

function parseDomCards(html, fallbackCurrency) {
  if (typeof DOMParser === "undefined") return [];
  const doc = new DOMParser().parseFromString(html, "text/html");
  const cards = [
    ...doc.querySelectorAll("li.ui-search-layout__item, div.ui-search-result, div.poly-card, ol.ui-search-layout > li"),
  ];
  const items = [];
  for (const card of cards) {
    const link =
      card.querySelector("a.poly-component__title, a.ui-search-link, a.ui-search-item__group__element, a[href*='/p/'], a[href*='MLA']") ||
      card.querySelector("a[href*='mercadolibre']");
    const titleEl =
      card.querySelector("h2, h3, a.poly-component__title, .ui-search-item__title, .poly-component__title");
    const frac = card.querySelector(".andes-money-amount__fraction");
    const cents = card.querySelector(".andes-money-amount__cents");
    const href = link?.href || link?.getAttribute("href");
    const title = text(titleEl?.textContent || link?.textContent);
    const price = parsePriceText(frac?.textContent, cents?.textContent);
    if (!title || !price || !href) continue;
    items.push({
      id: extractId(href),
      title,
      price,
      currency: fallbackCurrency,
      permalink: href.split("#")[0],
      thumbnail: card.querySelector("img")?.src || card.querySelector("img")?.getAttribute("data-src") || null,
      condition: null,
      seller: text(card.querySelector(".poly-component__seller, .ui-search-official-store-label")?.textContent) || null,
      shipping: text(card.querySelector(".poly-component__shipping, .ui-search-item__shipping")?.textContent) || null,
    });
  }
  return items;
}

function normalizeApiItem(row) {
  if (!row || typeof row !== "object") return { id: null };
  const price = toNumber(row.price ?? row.original_price);
  return {
    id: row.id || extractId(row.permalink || ""),
    title: text(row.title),
    price,
    currency: row.currency_id || null,
    permalink: row.permalink || null,
    thumbnail: row.thumbnail || row.secure_thumbnail || null,
    condition: row.condition || null,
    seller: row.seller?.nickname || row.seller?.id || null,
    shipping: row.shipping
      ? {
          free: Boolean(row.shipping.free_shipping),
          logistic_type: row.shipping.logistic_type || null,
        }
      : null,
    official_store: row.official_store_name || null,
  };
}

function normalizeLoose(row, fallbackCurrency) {
  if (!row || typeof row !== "object") return null;
  const title = text(row.title || row.name);
  const price = toNumber(row.price ?? row.amount ?? row.original_price);
  const permalink = row.permalink || row.url || row.link || null;
  if (!title || !price) return null;
  return {
    id: row.id || extractId(permalink || ""),
    title,
    price,
    currency: row.currency_id || row.currency || fallbackCurrency,
    permalink,
    thumbnail: row.thumbnail || row.image || null,
    condition: row.condition || null,
    seller: row.seller?.nickname || row.seller_id || null,
    shipping: row.shipping || null,
  };
}

function extractId(value) {
  const m = String(value || "").match(/\b(MLA|MLM|MLB|MLC|MCO|MLU|MLV|MPE)\d{6,}\b/i);
  return m ? m[0].toUpperCase() : null;
}

function guessSiteFromId(id) {
  const prefix = String(id).slice(0, 3).toUpperCase();
  return SITES[prefix] ? prefix : "MLA";
}

function slugify(query) {
  return query
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function parsePriceText(fraction, cents) {
  if (!fraction) return null;
  const whole = String(fraction).replace(/[^\d]/g, "");
  if (!whole) return null;
  const frac = String(cents || "").replace(/[^\d]/g, "");
  return frac ? Number(`${whole}.${frac}`) : Number(whole);
}

function toNumber(value) {
  if (value == null || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const n = Number(String(value).replace(/\./g, "").replace(",", "."));
  if (Number.isFinite(n)) return n;
  const digits = Number(String(value).replace(/[^\d.]/g, ""));
  return Number.isFinite(digits) ? digits : null;
}

function text(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, Number(n) || lo));
}

function dedupe(items) {
  const seen = new Set();
  const out = [];
  for (const item of items) {
    const key = item.id || item.permalink || item.title;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

function browserHeaders(siteId) {
  return { Accept: "application/json" };
}

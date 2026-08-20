# ML Price Bridge

Chrome extension + local Grok MCP so Grok can search Mercado Libre **using your logged-in browser session**. You log in yourself. The extension never sends cookies or passwords to Grok — only listing titles, prices, and links.

## Setup

### 1. Load the extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** and pick `ml-bridge/extension`
4. Pin **ML Price Bridge**

### 2. Log into Mercado Libre

Click the extension → **Open Mercado Libre** → sign in as usual (`mercadolibre.com.ar` for Argentina).

The popup should say **Mercado Libre: logged in**.

### 3. Let Grok start the bridge

The MCP `ml-bridge` is registered in your user Grok config. Starting a Grok session launches `server/ml_bridge.py` on `127.0.0.1:18765`.

Open the extension popup and click **Reconnect to Grok**. It should say **Grok bridge: connected**.

Use **Test search** in the popup first. If that returns prices, Grok can do the same.

## What Grok can call

- `ml_status` — extension + login check
- `ml_search` — one query
- `ml_search_many` — a whole parts list
- `ml_item` — one listing id (`MLA…`)

## Security

- HTTP bridge binds to localhost only
- Extension returns listing JSON only (no cookies, no checkout)
- Read-only searches; it does not buy, message, or edit listings
- Pairing token lives in `~/.grok/ml-bridge/token`

## Troubleshooting

| Popup | Fix |
|---|---|
| Mercado Libre: not logged in | Sign in on mercadolibre.com.ar in this Chrome profile |
| Grok not running | Start a Grok session, then Reconnect |
| Test search empty | Disable a strict ad blocker on ML, retry a simpler query |
| Grok says extension never connected | Open the popup once so the service worker wakes up |

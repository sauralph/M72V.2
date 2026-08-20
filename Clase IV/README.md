# Clase IV — Conectándose con sistemas que no cooperan

MCP local + extensión de Chrome para que **Grok CLI** busque en Mercado Libre usando **tu sesión logueada**. El modelo recibe títulos, precios y links; no recibe cookies.

Presentación: `Clase IV.md`. Código: `ml-bridge/`.

## Requisitos

- Google Chrome (o Chromium) con la extensión cargada
- Grok CLI con el MCP `ml-bridge` habilitado
- Estar logueado en `mercadolibre.com.ar` en **ese** perfil de Chrome
- Python 3.10+ (stdlib only: el server no tiene `requirements.txt`)

## Setup

1. Chrome → `chrome://extensions` → Developer mode → **Load unpacked** → `ml-bridge/extension`
2. Pin **ML Price Bridge** → **Open Mercado Libre** → iniciar sesión
3. Registrar el MCP (ruta absoluta al script de este repo):

   ```toml
   # ~/.grok/config.toml
   [mcp_servers.ml-bridge]
   command = "python3"
   args = ["…/M72V.2/Clase IV/ml-bridge/server/ml_bridge.py"]
   enabled = true
   ```

4. Abrir una sesión `grok`. En el popup: **Reconnect to Grok**. Debe decir **Grok bridge: connected**.
5. **Test search** en el popup. Si hay precios, el agente puede pedir lo mismo.

Detalle y troubleshooting: `ml-bridge/README.md`.

## Tools

| Tool | Uso |
|---|---|
| `ml_status` | Extensión + login |
| `ml_search` | Una query |
| `ml_search_many` | Lista de partes (un presupuesto) |
| `ml_item` | Un listing `MLA…` |

## Caso de la clase

Sesión Grok `01a020f3-c2bf-7920-b9da-7dcbef1f4045`: cotizar en MLA un server capaz de cargar el GGUF 1-bit de **Kimi K3** (~610 GB). El MCP oficial de Mercado Libre no conectó; `ml-bridge` sí. Carrito de referencia: **~$7,9M ARS** (R740 + 24×32 GB ECC + 4 TB NVMe).

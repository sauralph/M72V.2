---
marp: true
theme: uba
paginate: true
size: 16:9
---

<!-- _class: lead -->

# Conectándose con sistemas que no cooperan

## MCP + extensión de Chrome: Mercado Libre desde Grok CLI

**Mg. Ezequiel Nuske** · Ex Chief Data Officer
Laboratorio interdisciplinario de IA en organizaciones · Clase IV

---

# Agenda

1. Recap: MCP como **plugin** del agente (Clase III)
2. El problema: sistemas que **no te dan una API usable**
3. La hipótesis: prestarle al LLM **tu sesión de navegador**
4. Anatomía de `ml-bridge` (MCP + extensión)
5. Cada pieza en código
6. Caso vivo: cotizar un server para un modelo frontera
7. Trade-offs, límites y próximos pasos

---

# Recap · Clase III

<div class="columns">

<div>

**Qué teníamos**

- Un agente SQL empaquetado (API + Docker + IaC)
- Un **CLI-LLM** (Grok / Claude Code) sobre el repo
- **MCP** para hablar con DigitalOcean / AWS

</div>

<div>

**Supuesto implícito**

- El sistema de afuera **coopera**:
  - OAuth, API key, docs
  - Tools estables (`list_droplets`, `create_app`)
  - Un contrato HTTP que el agente puede firmar

</div>

</div>

> En la nube “de producto”, MCP alcanza. En el mundo real, **la mayoría de los sistemas no se dejan conectar así**.

---

# El problema en una slide

<div class="columns">

<div>

**Qué falla**

- El MCP / API oficial **no arranca** (auth, handshake, scopes)
- El listado público está vacío, recortado o bloqueado
- Login, cookies, CAPTCHA, geobloqueo
- Scrapers frágiles: se rompen cada semana

</div>

<div>

**Qué intentamos antes**

- Pedir una API key “de partner”: **meses**
- Pegar HTML en el prompt: ruido, sin sesión
- Puppeteer headless: otro login, otro ban
- “Fijate vos en el navegador”: el agente **no ve** lo que vos ves

</div>

</div>

**La pregunta**: ¿cómo le damos al LLM acceso a un sitio **logueado**, *sin* mandarle cookies y *sin* esperar a que el proveedor coopere?

> Necesitamos un puente entre **tu navegador** y **el agente**.

---

# Un caso concreto

- Pregunta: *“¿qué hardware necesito para correr Kimi K3 en local?”*
- Respuesta técnica: no es un desktop. Pesos oficiales **1,56 TB**; el GGUF 1-bit pide **~610 GB de RAM**.
- Segunda pregunta: *“tenés un MCP local que controla el browser de Mercado Libre: armá el presupuesto”*.
- El MCP **oficial** de Mercado Libre **no conectó**.
- El puente del lab sí: **sesión logueada en Chrome**, precios en vivo.

**Lo que queremos**: una cotización en minutos, con **avisos reales** (título, precio, link), no un número inventado.

---

<!-- _class: quote -->

# La hipótesis

> Si el sistema no te da una API,
> no le pedimos permiso al sistema.
> Le pedimos prestada **la sesión del usuario**.

Eso es un **browser bridge**: MCP hacia el agente, extensión hacia el sitio.

---

# ¿Qué es un sistema que no coopera?

<div class="columns">

<div>

**Señales típicas**

- OAuth / MCP oficial cae en el handshake
- API pública sin cookies → 0 resultados útiles
- El precio “de verdad” aparece **después** del login
- ToS + WAF + CAPTCHA contra bots
- Documentación para partners, no para un lab

</div>

<div>

**No es un bug del agente**

- Grok puede llamar tools
- El tool **no tiene con qué autenticarse**
- El usuario **sí** está adentro, en Chrome

**Implicancia**

- El recurso escaso no es el LLM.
- Es **la sesión humana** ya negociada con el sitio.

</div>

</div>

> Clase III: MCP contra APIs que cooperan.  
> Clase IV: MCP contra **la web que usás todos los días**.

---

# Dos caminos a Mercado Libre

| Camino | Qué es | Qué pasó en el lab |
|---|---|---|
| MCP oficial `mercadolibre` | HTTP remoto, token de app | Handshake **falló**; el agente no vio tools |
| `ml-bridge` | MCP **stdio local** + extensión Chrome | 4 tools vivas, sesión **logged in** |

El oficial es el diseño “lindo”: el proveedor te invita.  
El bridge es el diseño **honesto** cuando el proveedor no te invita.

> Misma pregunta, dos conectores. Solo uno devolvió precios.

---

# Anatomía de `ml-bridge`

```text
 Grok CLI  ──stdio MCP──►  ml_bridge.py  ──HTTP 127.0.0.1:18765──►  extensión Chrome
                                                                    │
                                                                    │  cookies de *tu* perfil
                                                                    ▼
                                                           Mercado Libre (MLA)
                                                                    │
                                                                    ▼
                                              JSON: título · precio · link  (sin cookies)
```

**Cinco piezas**, cada una con una responsabilidad clara:

1. **Grok** descubre y llama tools (`ml_search`, `ml_search_many`, …)
2. **MCP stdio** traduce tool-call → job en una cola
3. **HTTP local** (solo localhost) entrega el job a la extensión
4. **Extensión** busca con la sesión logueada
5. **Resultado** vuelve al modelo como JSON de listings

---

# Stack del lab

| Pieza | Tecnología | Por qué |
|---|---|---|
| Agente | **Grok CLI** | Ya habla MCP; no reescribimos el host |
| MCP server | `ml_bridge.py` *(~400 líneas)* | stdio + cola + HTTP, sin frameworks |
| Puente | `127.0.0.1:18765` | Nunca sale de la máquina |
| Navegador | Extensión **MV3** “ML Price Bridge” | Usa *tu* login, no el del modelo |
| Sitio | Mercado Libre Argentina (`MLA`) | Precios locales, en ARS |

**Tools**: `ml_status`, `ml_search`, `ml_search_many`, `ml_item`.

> Sin Playwright en el agente, sin cookies en el prompt, sin API key de partner. **A propósito.**

---

# Setup en 4 pasos

1. **Cargar la extensión**  
   `chrome://extensions` → Developer mode → *Load unpacked* → `Clase IV/ml-bridge/extension`
2. **Loguearte vos**  
   Popup → *Open Mercado Libre* → entrar como siempre. Debe decir **Mercado Libre: logged in**.
3. **Arrancar Grok** (levanta el MCP)  
   En `~/.grok/config.toml`:

```toml
[mcp_servers.ml-bridge]
command = "python3"
args = ["Clase IV/ml-bridge/server/ml_bridge.py"]
```

4. **Reconnect to Grok** en el popup → **Grok bridge: connected**.  
   *Test search* primero. Si ves precios, Grok puede pedir lo mismo.

---

# Las 4 tools

| Tool | Para qué | Input típico |
|---|---|---|
| `ml_status` | ¿Extensión viva? ¿Login OK? | `site=MLA` |
| `ml_search` | Una búsqueda | `query`, `sort=price_asc`, `condition=new` |
| `ml_search_many` | Una lista de partes | `[{id, query}, …]` |
| `ml_item` | Un aviso por id | `MLA…` |

En Grok las ves namespaced: `ml-bridge__ml_search`.

```bash
grok mcp list
grok mcp doctor ml-bridge
# En la sesión: “Listá los MCP conectados”
```

> `ml_search_many` es el atajo para **armar un carrito**. Una tool-call, N búsquedas.

---

<!-- _class: code-slide -->

# Paso 1 · El MCP es una cola de jobs

**Grok llama la tool; Python no scrapea.** Encola un job, espera a que la extensión lo resuelva, y devuelve JSON.

```python
def submit_job(action: str, args: dict, timeout: float = 45) -> dict:
    job_id = uuid.uuid4().hex
    waiter = JobWaiter()
    _waiters[job_id] = waiter
    _jobs.put({"id": job_id, "action": action, **args})
    if not waiter.event.wait(timeout):
        return {"ok": False, "error": "The Chrome extension did not pick up the job."}
    payload = waiter.payload or {}
    if not payload.get("ok"):
        return {"ok": False, "error": payload.get("error")}
    return {"ok": True, "data": payload.get("data")}
```

> El LLM **nunca** habla con Mercado Libre. Habla con un proceso local.

---

<!-- _class: code-slide -->

# Paso 2 · La extensión hace long-poll

**Service worker MV3**: pide el próximo job a localhost, corre la búsqueda, postea el resultado. Token en `X-Bridge-Token`.

```javascript
const res = await fetch(`${BRIDGE}/v1/next?wait=20`, {
  headers: tokenHeaders(token),
});
if (res.status === 204) continue;          // nada en la cola
const job = await res.json();
const result = await runJob(job);          // search | search_many | item | status
await fetch(`${BRIDGE}/v1/result`, {
  method: "POST",
  headers: { "Content-Type": "application/json", ...tokenHeaders(token) },
  body: JSON.stringify(result),
});
```

> Si Grok no está corriendo, el popup dice **Grok not running**. No hay magia: hay un proceso escuchando.

---

<!-- _class: code-slide -->

# Paso 3 · Tres intentos de búsqueda

**La API pública a menudo no alcanza.** La extensión degrada: API → HTML de listado → una tab con tu sesión.

```javascript
const apiItems = await searchApi(siteId, query, limit, condition, sort);
if (apiItems.length) return { source: "api", results: apiItems };

const htmlItems = await searchListado(site, siteId, query, ...);
if (htmlItems.length) return { source: "listado", results: htmlItems };

const tabItems = await searchViaTab(site, query, ...);
if (tabItems.length) return { source: "tab", results: tabItems };
```

En la sesión del lab, casi todo salió por `source: "tab"`: **hace falta el navegador logueado**.

> Si la extracción es ruidosa, **todo el presupuesto hereda el ruido**. Igual que el PDF en Clase I.

---

# Qué *no* viaja al modelo

<div class="columns">

<div>

**Se queda en Chrome**

- Cookies (`ssid`, `sid`, …)
- Password, 2FA, checkout
- El HTML crudo de la página
- Mensajes, compras, datos de cuenta

</div>

<div>

**Llega a Grok**

- `title`, `price`, `currency`, `permalink`
- `id` del listing (`MLA…`)
- `source` (`api` / `listado` / `tab`)
- `loggedIn: true` y un conteo de cookies — **no las cookies**

</div>

</div>

HTTP del puente: **solo** `127.0.0.1`. Token de pairing en `~/.grok/ml-bridge/token` (`0600`).  
La extensión es **read-only**: no compra, no chatea, no edita avisos.

> El modelo ve **el mercado**. No ve **tu identidad**.

---

<!-- _class: quote -->

# Caso vivo

> Sesión `01a020f3-c2bf-7920-b9da-7dcbef1f4045`  
> *“Local Kimi3 model hardware requirements”*  
> 20 de agosto de 2026 · Grok 4.6 + `ml-bridge`

De una pregunta de hardware a un **carrito cotizado en Mercado Libre**.

---

# Prompt 1 · el modelo frontera

```text
what kind of hardware do I need to run a local kimi3 model?
```

**Kimi K3 no es un modelo de desktop.** MoE de 2,8T parámetros (104B activos), visión nativa, contexto de 1M.

| Objetivo | Memoria | Hardware que entra |
|---|---|---|
| Serving oficial (vLLM / SGLang) | **~1,68 TB de VRAM** | **8× B300 / GB300** |
| GGUF 1-bit (Unsloth) | **~610 GB RAM+VRAM** | Dual-socket “RAM monster” |
| GGUF 2-bit | **~726–880 GB** | La misma clase, más memoria |
| Q8 / pesos nativos | **~1,6 TB** | Cluster, no workstation |

> Una 4090, una 5090 o un Mac de 128 GB **no corren K3** de forma útil.  
> Hay que cotizar un **server**, no una PC gamer.

---

# Prompt 2 · el puente entra en escena

```text
you have access to a local mcp controlling a MercadoLibre browser,
do a budget for such a computer
```

Lo que el runtime le dijo al modelo, en esa sesión:

```text
MCP servers connected:
- ml-bridge (4 tools)

MCP servers that failed to connect:
- mercadolibre  (handshake failed)
```

Grok no “se inventó” Mercado Libre. Primero hizo `ml_status`:

```json
{ "session": { "host": "www.mercadolibre.com.ar",
               "loggedIn": true, "cookieCount": 44 } }
```

> Sesión humana viva. Recién ahí disparó `ml_search_many` sobre RAM ECC, chasis, NVMe y GPUs.

---

# Lo que trajo el puente (ejemplos reales)

Búsquedas en **MLA**, `source: "tab"`, precios del día. Ruido incluido: el listado mezcla avisos.

| Query | Hallazgo usable | Precio |
|---|---|---|
| `Samsung 32GB ECC registered PC4` | Samsung PC4-2666V 32 GB | **$170.000** |
| `servidor dell r740` | PowerEdge R740 usado | **$1.999.000** |
| `ssd samsung 990 pro 4tb` | 990 Pro 4 TB | **$1.799.999** |
| `RTX 3090 24GB` | Zotac 3090 OC 24 GB | **$1.915.000** |
| `RTX 5090 32GB` | Palit GameRock 32 GB | **$7.780.499** |

`ml_item` se cayó a mitad de sesión: el agente **siguió con precios de búsqueda** y lo declaró. Eso es auditabilidad, no cosmética.

---

# El carrito que sí carga el 1-bit

**Target**: 768 GB DDR4 ECC + 4 TB NVMe. llama.cpp / Unsloth. Unos pocos tokens/s. Calidad ~79% top-1 vs. el modelo real.

| Qty | Pieza | Listing | Línea |
|---|---|---|---|
| 1 | Chasis 24 DIMM | Dell PowerEdge R740 (usado) | $1.999.000 |
| 24 | 32 GB DDR4-2666 ECC RDIMM | Samsung PC4-2666V | **$4.080.000** |
| 1 | 4 TB NVMe | Samsung 990 Pro | $1.799.999 |
| | **Para cargar K3 1-bit en RAM** | | **~$7,9 millones** |

La RAM es **la mayor parte de la factura**. Mercado Libre **no vende** el nodo que Moonshot pide (8× B300, ~1,7 TB de VRAM).

---

# Tres totales, una lección

| Build | Qué obtenés | Carrito ML |
|---|---|---|
| **A. Homelab 1-bit** | 768 GB + 4 TB + dual Xeon, sin GPU | **~$7,9M** |
| **B. Homelab “más lindo”** | G10 40-core + 768 GB + 8 TB + 3090 | **~$13–16M** |
| **C. Server 1 TB nuevo** | Dell R770 dual Xeon, 1 TB DDR5 | **$129M** |

C **sigue sin ser** un nodo vLLM de K3. A es el primer build en ML que **entra en RAM** el GGUF 1-bit.

**Lo que no hay que comprar para este modelo**

- Mac Studio M4 Max ~$7M (listings de 36 GB)
- Una o cuatro 5090: 32–128 GB de VRAM vs. 610 GB del quant
- Un R610/R710 con 128 GB: DDR3, corto de memoria

---

# El agente también dijo *no*

1. **Stock**: un aviso a $170.000 ≠ 24 sticks idénticos en carrito.
2. **Tipo de RAM**: no mezclar RDIMM y LRDIMM; el board no bootea.
3. **Física**: 400–800 W, ruido de rack.
4. **Esto no es K3 nativo**: MXFP4 son 1,56 TB y ocho GPUs de 288 GB. ML no lo vende.
5. **Velocidad**: dual Xeon + DDR4-2666 carga el 1-bit; **no se siente como la API de Kimi**.

> Si el objetivo es *usar* K3, la API es más barata que el carrito A.  
> Si el objetivo es *tener los pesos en casa*, **~$8 millones** es el primer número anclado a listings.

---

# Demo guiada · Grok CLI + `ml-bridge`

1. Extensión cargada, ML logueado, popup en **connected**
2. `grok` en el repo `M72V.2`
3. “Listá los MCP conectados y corré `ml_status`”
4. “Buscá en Mercado Libre un Dell R740 y RAM ECC de 32 GB; ordená por precio”
5. “Armá un presupuesto para un server de 768 GB que pueda cargar un GGUF de ~610 GB”
6. Pedile **links** a cada ítem. Si un aviso es un PC gamer colado en la query, que lo **descarte**

> El valor no es “scraper + Excel”. Es **un agente que cotiza y cita**, en el mismo loop en el que razona el hardware.

---

# Trade-offs del browser bridge

| Decisión | Si va **corto** | Si va **largo** |
|---|---|---|
| Depender de la sesión humana | El agente no ve precios logueados | El usuario tiene que estar *ahí*, con Chrome abierto |
| Extraer listings (no HTML) | El modelo no puede re-parsear | Perdés atributos que no mapeamos |
| `ml_search_many` | N round-trips, lento | Una call pesada; listings duplicados / ruidosos |
| Fallback a `tab` | API vacía = “no hay nada” | Abre pestañas, más frágil, más visible |

**Default del lab**: `sort=price_asc`, `condition=new`, `site=MLA`, timeout 45 s (90 s en `search_many`).

> No hay un conector universal. Hay que **medir** contra el sitio real, logueado, hoy.

---

# Cuándo NO alcanza este puente

<div class="columns">

<div>

**Producto / escala**

- Multi-usuario → cada uno con su Chrome no escala
- Jobs sin persona delante → la sesión expira
- ToS / robots: un lab ≠ un crawler 24/7
- Comprar, chatear, publicar: **fuera de alcance** (y a propósito)

</div>

<div>

**Calidad de datos**

- Listings sucios (una 4090 que es un PC armado)
- Duplicados, avisos reacondicionados mezclados
- `ml_item` intermitente → no cerrar stock sin abrir el link
- Precios en ARS, sin IVA / envío / recargo

**Seguridad**

- La extensión *ve* cookies: tratarla como privilegio de root del browser

</div>

</div>

---

# Relación con I, II y III

```text
Clase I    tus PDFs     → RAG local
Clase II   tu SQLite    → agente SQL
Clase III  tu nube      → MCP de APIs que cooperan
Clase IV   tu navegador → MCP + extensión, APIs que no cooperan
```

Mismo espíritu: **mínimo legible**, cada pieza se abre en clase, el modelo no se traga secretos que no necesita.

El patrón que se repite: **un puente estrecho** (chunks, schema, tools, listings) entre un mundo privado y la generación.

---

<!-- _class: lead -->

# El número que importa

<div class="big-number">0</div>

**cookies en el prompt. ~$8 millones cotizados con avisos reales.**
*Un puente honesto hacia un sitio que no nos invitó.*

Suficiente para prototipar, enseñar y decidir *si vale la pena comprar*, antes de scrapers y partners.

---

# Lecciones aprendidas

1. **MCP no es magia**: si el handshake oficial falla, el agente se queda ciego.
2. **La sesión del usuario es un recurso**: más valiosa que una API key que no te dan.
3. **Separar secretos de hechos**: cookies en Chrome, precios en el LLM.
4. **Localhost es el perímetro**: el puente no necesita “la nube”.
5. **Los listings mienten un poco**: hay que filtrar, citar el link, declarar cuando `ml_item` falla.
6. **Un modelo frontera no se cotiza de memoria**: sin precios vivos, el presupuesto es fanfic.

---

<!-- _class: lead -->

# Para la discusión

¿Qué sistema de tu organización **no coopera** hoy —un ERP, un banco, un expediente, un marketplace— y ya está abierto en el browser de alguien?

¿Prefieren **esperar la API oficial**, o un puente mínimo que cotice / consulte **con la sesión humana**, auditando qué sale del navegador?

---

<!-- _class: closing -->

# ¡Gracias!

**Ezequiel Nuske**

<div class="columns">

<div>

![w:170 h:170](style/qr-email.png)

**Email**
eonuske@mail.austral.edu.ar

</div>

<div>

![w:170 h:170](style/qr-linkedin.png)

**LinkedIn**
https://www.linkedin.com/in/ezequiel-nuske-15137862/

</div>

</div>

*Preguntas y respuestas · `Clase IV/ml-bridge/`*

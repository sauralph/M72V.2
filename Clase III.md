---
marp: true
theme: uba
paginate: true
size: 16:9
---

<!-- _class: lead -->

# Del bonus al aire

## Toy production del agente SQL · CLI agents · MCP · IaC

**Mg. Ezequiel Nuske** · Ex Chief Data Officer
Laboratorio interdisciplinario de IA en organizaciones · Clase III

---

# Agenda

1. Recap: el **bonus de Clase II** (Streamlit)
2. Qué hay que **modificar** para una versión “prod toy”
3. El artefacto: `Clase III/` en ~200 líneas + Docker
4. Instalar un **CLI-LLM**: Grok · Claude Code · genérico
5. ¿Qué es un **MCP**?
6. MCP de **DigitalOcean** y **AWS**
7. Despliegue mínimo con **infraestructura como código**
8. Cierre y límites honestos

---

# Recap · Bonus de Clase II

<div class="columns">

<div>

**Qué era**

- GUI Streamlit sobre `sql_agent_ollama.py`
- Misma lógica del CLI: no se duplicaba el agente
- Pregunta → SQL → tabla → gráfico
- Ideal para **demo en la laptop**

</div>

<div>

**Límites para “producción”**

- Proceso de desarrollo (`streamlit run`)
- Acoplado a Ollama local
- Sin contrato HTTP estable
- Sin contenedor ni healthcheck
- Sin forma de desplegarlo en la nube en 10 min

</div>

</div>

> El bonus demuestra el **producto**. Esta clase cierra el loop: **empaquetar y operar**.

---

# La pregunta de esta clase

<div class="columns">

<div>

**Lab**

- Script + Streamlit
- Modelo en tu máquina
- DB en disco
- “Corre en mi notebook”

</div>

<div>

**Toy production**

- API con contrato JSON
- UI estática o thin client
- Config por entorno
- Imagen Docker reproducible
- Un `terraform apply` que deja una URL pública

</div>

</div>

**No es producción bancaria.** Es el mínimo que un equipo de datos/IA debería poder **versionar, desplegar y explicar**.

---

<!-- _class: quote -->

# Hipótesis

> Si el agente de Clase II es el *cerebro*,
> el bonus Streamlit es la *demo*,
> entonces la toy-production es el *esqueleto operativo*:
> API · config · contenedor · IaC · herramientas de agente en la terminal.

---

# Modificaciones requeridas (mapa)

| De (bonus) | A (toy-prod) | Por qué |
|---|---|---|
| Streamlit | **FastAPI** + HTML mínimo | Contrato HTTP, health, deploy simple |
| Import del agente CLI | Módulo `app/agent.py` autocontenido | Imagen sin depender de `Clase II/` |
| Ollama `/api/generate` | **OpenAI-compatible** `/v1` (fallback solo con Ollama) | Cambiar de proveedor sin reescribir |
| Variables en código | `REAL_ESTATE_DB`, `LLM_*` | 12-factor / secrets en la nube |
| Sin health | `GET /health` | Load balancer, App Platform, k8s |
| `pip` local | **Dockerfile** multi-paso simple | Reproducible en CI y en DO/AWS |
| “Corré esto” | **Terraform** App Platform | Infra declarativa, no clickops |
| DB en `Clase II/` | Copia en `data/real_estate.db` | Self-contained en el deploy |

---

# Anatomía del artefacto

```text
Clase III/
├── app/
│   ├── agent.py          # NL → SQL → respuesta (read-only)
│   ├── api.py            # FastAPI: /health /meta /ask /
│   └── static/index.html # UI mínima (sin Streamlit)
├── data/real_estate.db   # copia de Clase II (+ toy opcional)
├── Dockerfile
├── docker-compose.yml    # API → Ollama del host
├── infra/main.tf         # DigitalOcean App Platform
└── requirements.txt      # fastapi, uvicorn, requests
```

**Flujo runtime**

```text
Browser ──POST /ask──► FastAPI ──► agent_answer
                                      │
                         schema → LLM plan → SQL ro → summarize
                                      │
Browser ◄── JSON {answer, sql, cols, rows}
```

---

# Cambio 1 · De GUI a API

<div class="columns">

<div>

**Antes (Streamlit)**

- Estado en `st.session_state`
- Reruns mágicos
- Difícil de integrar con otro front
- Difícil de monitorear

</div>

<div>

**Ahora (FastAPI)**

```http
POST /ask
{"question":"Precio promedio por dormitorios"}

→ 200
{
  "answer": "...",
  "sql": "SELECT ...",
  "cols": ["bedrooms","avg"],
  "rows": [[2, 95000], ...],
  "elapsed_s": 4.2
}
```

</div>

</div>

La UI es un **cliente** del API. Mañana puede ser React, un bot de Slack o un CLI.

---

# Cambio 2 · LLM intercambiable

```bash
# Local con Ollama (default)
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=llama3.1
export LLM_API_KEY=ollama

# Nube: DO Serverless Inference (lo que usa la demo)
export LLM_BASE_URL=https://inference.do-ai.run/v1
export LLM_MODEL=llama-4-maverick
export LLM_API_KEY=...   # Model Access Key de DO
```

**Regla de diseño**: el agente habla el dialecto **OpenAI Chat Completions**.  
Ollama lo expone en `/v1`; DO, OpenAI, vLLM o LiteLLM también. Se cambia el LLM sin tocar el SQL.

> En producción real: secretos en el vault del proveedor, nunca en el repo.

---

# Cambio 3 · Seguridad mínima que ya teníamos

Se **conserva** del agente de Clase II:

- SQLite `?mode=ro` (solo lectura)
- Whitelist `SELECT` / `WITH`
- Cap de filas (`LIMIT` + `fetchmany`)
- Sin `ATTACH`, sin `PRAGMA` desde el LLM

Se **suma** en toy-prod:

- Usuario no-root en el contenedor
- DB montada `:ro`
- Healthcheck HTTP
- Timeouts al LLM

Todavía **falta** (y hay que decirlo en clase): auth, rate limit, audit log, PII redaction.

---

# Cómo correrlo en 60 segundos

```bash
cd "Clase III"
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ollama pull llama3.1

uvicorn app.api:app --reload --port 8000
# → http://localhost:8000
```

La DB completa ya está en `data/real_estate.db` (default). Seed chico:

```bash
REAL_ESTATE_DB=./data/toy_real_estate.db \
  uvicorn app.api:app --port 8000
```

**Con Docker**

```bash
docker compose up --build
```

---

<!-- _class: quote -->

# Segunda mitad de la clase

> Un agente en producción no se opera solo con la UI.
> Se opera con **herramientas en la terminal** y con **conectores al cloud**.
> Ahí entran los **CLI-LLM** y los **MCP**.

---

# ¿Qué es un CLI-LLM?

Un **agente de código en la terminal**: lee tu repo, edita archivos, corre comandos y (con permisos) habla con servicios externos.

| Herramienta | Quién | Idea |
|---|---|---|
| **Claude Code** | Anthropic | Agente CLI profundo sobre el workspace |
| **Grok** (Grok Build / CLI) | xAI | Agente en terminal + skills + MCP |
| **Aider / Continue / genérico** | open | LLM + diff + git en el loop |
| **`llm` (Simon Willison)** | open | CLI minimalista multi-proveedor |

**Para esta clase**: cualquiera sirve. Lo importante es el **patrón**: prompt → herramientas → diff → verificación.

---

# Instalar Claude Code

```bash
# Requiere Node 18+
npm install -g @anthropic-ai/claude-code

# Auth (navegador o API key)
claude
# o: export ANTHROPIC_API_KEY=sk-ant-...
```

**Uso típico en este repo**

```bash
cd /ruta/M72V.2
claude
# "Revisá Clase III y proponé un healthcheck más estricto"
```

Documentación oficial: `https://docs.anthropic.com/en/docs/claude-code`

> Tip didáctico: pedile al CLI que **explique el Dockerfile** antes de tocarlo.

---

# Instalar Grok (CLI / Grok Build)

```bash
# Según el canal que uses en el curso (binario o npm del entorno del lab)
# Ejemplo conceptual:
#   curl -fsSL https://... | sh
#   o el instalador que indique la doc de xAI / Grok Build

grok   # o el binario del TUI del lab
```

**Patrones útiles**

- “Generá el PDF de `Clase III.md` con Marp”
- “Explicá el `main.tf` y listá secrets faltantes”
- Skills del entorno: review, docker, terraform

> En el lab ya usamos el agente sobre este monorepo: **misma idea**, distinto proveedor.

---

# CLI genérico multi-proveedor (`llm`)

Para no casarse con un vendor en la demo:

```bash
pip install llm
llm keys set openai          # o openrouter, etc.
llm "Explicá qué hace /health en una API FastAPI"

# Con un modelo local vía Ollama
llm install llm-ollama
llm -m llama3.1 "Resumí este README" < README.md
```

**Mensaje de la slide**: el *wrapper* CLI es intercambiable; lo que importa es  
**contexto del repo + herramientas + verificación**.

---

# ¿Qué es un MCP?

**Model Context Protocol** — estándar abierto para conectar un LLM/agente a **herramientas y datos** de forma estructurada.

```text
┌─────────────┐     MCP      ┌──────────────────┐
│  Host LLM   │◄────────────►│  MCP Server      │
│ Claude/Grok │   tools +    │  (DO, AWS, DB…)  │
│  Cursor…    │   resources  │                  │
└─────────────┘              └──────────────────┘
```

| Concepto | Analogía |
|---|---|
| **Host** | El IDE / CLI agente |
| **MCP server** | Un “plugin” que expone tools |
| **Tool** | Acción: `list_droplets`, `create_app`… |
| **Resource** | Lectura de contexto (logs, specs) |

> Sin MCP: el agente solo ve archivos.  
> Con MCP: el agente puede **operar tu nube** con permisos explícitos.

---

# Por qué MCP importa en *esta* clase

<div class="columns">

<div>

**Antes**

1. Escribís Terraform a mano
2. Corrés `doctl` / `aws` a mano
3. Copiás errores al chat
4. Perdés el hilo

</div>

<div>

**Con MCP de cloud**

1. El agente lee `infra/main.tf`
2. Lista apps/droplets vía MCP
3. Propone un `plan` / cambio
4. Vos **aprobás** la acción riesgosa

</div>

</div>

MCP no reemplaza IaC: **lo complementa**.  
IaC declara el estado deseado; MCP acelera la **operación y el diagnóstico**.

---

# Instalar DigitalOcean MCP

Idea: el agente habla con tu cuenta DO (apps, droplets, DBs) vía tools MCP.

```bash
# 1) Token de API (solo lectura para demos)
#    Cloud → API → Generate New Token
export DIGITALOCEAN_TOKEN=dop_v1_...

# 2) Registrar el server MCP en el host (ejemplo genérico JSON)
#    ~/.config/<host>/mcp.json  o  settings del CLI
```

```json
{
  "mcpServers": {
    "digitalocean": {
      "command": "npx",
      "args": ["-y", "@digitalocean/mcp"],
      "env": { "DIGITALOCEAN_TOKEN": "dop_v1_..." }
    }
  }
}
```

> El paquete exacto puede versionarse: verificá la doc actual de DigitalOcean MCP.  
> **Principio**: token en env, scope mínimo, nunca en git.

---

# Instalar AWS MCP (patrón)

Mismo patrón, otro cloud:

```bash
# Credenciales (SSO o access keys de laboratorio)
aws configure sso
# o: export AWS_PROFILE=lab-readonly
```

```json
{
  "mcpServers": {
    "aws": {
      "command": "uvx",
      "args": ["awslabs.core-mcp-server@latest"],
      "env": {
        "AWS_PROFILE": "lab-readonly",
        "AWS_REGION": "us-east-1"
      }
    }
  }
}
```

**Buenas prácticas de clase**

- Cuenta **sandbox**, no producción
- IAM de **solo lectura** para la primera hora
- Acciones de escritura: confirmación humana obligatoria

---

# Demo guiada · MCP + este repo

1. Abrí el CLI-LLM en `M72V.2`
2. “Listá los MCP conectados”
3. “Leé `Clase III/infra/main.tf` y explicá qué crea”
4. Con DO MCP: “¿Está sana la app `sql-agent-toy`? ¿Qué `LLM_MODEL` usa?”
5. “Mostrame los logs del último deploy” · “¿qué modelos serverless hay?”
6. Revisá secrets: `TF_VAR_inference_api_key`, `DIGITALOCEAN_TOKEN`

**Regla de oro**: el agente propone; **vos** aplicás cambios costosos o irreversibles.

---

# Infraestructura como código (IaC)

**Definición operativa**: el entorno se describe en archivos versionados.  
Aplicar dos veces deja el mismo resultado (convergencia).

| Enfoque | Ejemplo en esta clase |
|---|---|
| Imperativo | `doctl apps create ...` clickops |
| Declarativo | `infra/main.tf` + `terraform apply` |
| Local prod-like | `docker-compose.yml` |

```text
Código app  ──►  imagen Docker  ──►  servicio en App Platform
     ▲                                      │
     └──────── git + Terraform ─────────────┘
```

---

# El `main.tf` en una slide · un switch de backend

```hcl
variable "llm_backend" { default = "serverless" }   # | "ollama_gpu"

resource "digitalocean_droplet" "ollama" {           # solo si ollama_gpu
  count     = local.use_gpu ? 1 : 0
  size      = "gpu-6000adax1-48gb"
  user_data = templatefile("cloud-init-ollama.yaml", { ollama_model = "llama3.1" })
}

resource "digitalocean_app" "sql_agent" {            # FastAPI en CPU barato
  git { repo_clone_url = var.repo_clone_url }       # repo público, sin GitHub app
  env { key = "LLM_BASE_URL" value = local.llm_base_url }   # DO serverless | GPU /v1
  env { key = "LLM_MODEL"    value = local.llm_model }      # llama-4-maverick | llama3.1
  env { key = "LLM_API_KEY"  value = local.llm_api_key  type = "SECRET" }
  health_check { http_path = "/health" }
}
```

**Qué declara**: el agente + *a dónde habla* (serverless o GPU propio).  
**Qué no**: VPC privada, auth, autoscaling, DB gestionada.

---

# Despliegue mínimo paso a paso · serverless

```bash
export DIGITALOCEAN_TOKEN=dop_v1_...
export TF_VAR_inference_api_key=...   # Model Access Key (consola DO → Inference)

cd "Clase III/infra"
terraform init && terraform plan      # 1 recurso: la app
terraform apply                       # ~3–5 min: build del Dockerfile

URL=$(terraform output -raw live_url)
curl -s $URL/health | jq
curl -s -X POST $URL/ask -H 'Content-Type: application/json' \
  -d '{"question":"¿Cuántas propiedades hay por dormitorios?"}' | jq

terraform destroy                     # al terminar la clase
```

Variante GPU: `llm_backend = "ollama_gpu"` en `terraform.tfvars` → 4 recursos, 5–15 min de boot, **~US$1,57/h**.

---

# Diagrama del despliegue toy

<div class="columns">

<div>

**A · `serverless` (la demo)**

```text
Usuario ──HTTPS──►
  App Platform
  FastAPI + SQLite
        │ LLM_BASE_URL
        │ inference.do-ai.run/v1
        ▼
  DO Serverless Inference
  llama-4-maverick
```

~US$5/mes + tokens

</div>

<div>

**B · `ollama_gpu`**

```text
Usuario ──HTTPS──►
  App Platform
  FastAPI + SQLite
        │ LLM_BASE_URL
        │ http://<gpu-ip>:11434/v1
        ▼
  GPU Droplet
  Ollama · llama3.1
```

~US$5/mes + **~US$1,57/hora** de GPU

</div>

</div>

Mismo contenedor, mismo código: **solo cambian 3 variables de entorno**. SQLite viaja dentro de la imagen.

---

# Demo en vivo

**<https://sql-agent-toy-pwkwf.ondigitalocean.app>**

| Pregunta | SQL generado | Tiempo |
|---|---|---|
| ¿Cuántas propiedades hay por dormitorios? | `SELECT bedrooms, COUNT(*) … GROUP BY bedrooms` | ~7 s |
| Top 5 más caras en USD con dirección | `SELECT address, price_usd … ORDER BY price_usd DESC LIMIT 5` | ~8 s |

- `GET /health` → DB + alcance del LLM · `GET /meta` → tablas y ejemplos
- Probala desde la UI (`/`) o con `curl` — **sin auth: cada pregunta gasta tokens**

---

# Lo que se rompió al desplegar (y por qué importa)

| Síntoma | Causa | Lección |
|---|---|---|
| `/ask` → `localhost:11434 refused` | El fallback a Ollama **tapaba** el error real del proveedor | Un fallback silencioso es un bug: mostrá el error original |
| `LLM HTTP 404 model not found` | `llama3.3-70b-instruct` salió del catálogo serverless | El catálogo cambia: el modelo es **config**, no código |
| `/health` OK pero `/ask` falla | El health solo prueba alcance, no una inferencia | Health ≠ smoke test end-to-end |

Arreglo: un commit al agente + cambiar `LLM_MODEL` en App Platform. **Sin tocar el SQL.**

---

# Compose local vs nube

<div class="columns">

<div>

**`docker compose`**

- API en `:8000`
- Ollama en el **host**
- DB montada `:ro`
- Ideal para ensayo y CI smoke

```bash
docker compose up --build
curl localhost:8000/health
```

</div>

<div>

**Terraform + App Platform**

- Build en la nube desde el repo
- Key del LLM como `SECRET`
- URL HTTPS gestionada
- Healthcheck nativo
- 1 instancia (0,5 GB · ~US$5/mes)

```bash
terraform apply
```

</div>

</div>

Misma **imagen mental**: proceso stateless + config por env + health.

---

# Checklist de la clase (alumnos)

1. Correr `uvicorn` local con `data/real_estate.db`  
2. Hacer una pregunta y **leer el SQL** generado  
3. Cambiar `LLM_MODEL` y repetir  
4. `docker compose up` y pegarle a `/health`  
5. Instalar **un** CLI-LLM (Claude Code, Grok o `llm`)  
6. Configurar **un** MCP de cloud en modo lectura  
7. Pegarle a la **demo en vivo** y comparar el SQL con el local  
8. Leer `infra/main.tf`: ¿qué cambia entre `serverless` y `ollama_gpu`?  
9. *(Opcional)* `terraform plan` — apply solo con cuota/lab

---

# Límites honestos del “toy”

| Tema | Estado |
|---|---|
| Auth / multi-usuario | No |
| Observabilidad (métricas, traces) | No |
| DB gestionada / backups | No (SQLite en imagen) |
| GPU / Ollama en la nube | Opcional (`ollama_gpu`); la demo usa LLM serverless |
| Gráficos matplotlib | Recortados en toy (JSON only) |
| Cumplimiento / PII | No evaluado |

**Para el siguiente salto**: Postgres + migrations, API keys de producto, cola de jobs, evaluation set de preguntas SQL, y budget de tokens.

---

# Relación con Clase I y Clase II

```text
Clase I   RAG local (PDF → embeddings → respuesta)
Clase II  Agente SQL + bonus Streamlit
Clase III Empaquetar el bonus: API · Docker · CLI · MCP · IaC
```

Mismo espíritu del laboratorio: **mínimo legible**, sin frameworks opacos, cada pieza se puede abrir en clase.

---

<!-- _class: lead -->

# Cierre

## Del notebook a una URL

**Agente claro · contrato HTTP · contenedor · secretos · IaC · MCP para operar**

Pregunta final: *¿qué es lo mínimo que tu organización necesita para confiar en un agente en producción?*

Gracias · consultas · `Clase III/README.md`

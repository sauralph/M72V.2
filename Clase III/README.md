# Clase III — Toy production del bonus de Clase II

Toma la GUI Streamlit del bonus (`Clase II/bonus/`) y la convierte en una
**versión mínima desplegable**: API HTTP + UI estática + Docker + IaC.

| Lab (Clase II bonus) | Toy production (esta carpeta) |
|---|---|
| Streamlit monolito | FastAPI + `static/index.html` |
| Ollama nativo hardcodeado | Cliente OpenAI-compatible (Ollama `/v1`, DO Serverless Inference u otro) |
| `python streamlit run` en la laptop | Docker + healthcheck |
| Sin infra | `docker-compose` + Terraform (DO App Platform) |
| DB en carpeta del lab | Copia en `data/real_estate.db` (+ seed toy opcional) |

## Requisitos

- Python 3.11+
- Ollama local **o** una API OpenAI-compatible (`LLM_BASE_URL` + `LLM_API_KEY`;
  ver opciones en `.env.example`)
- Docker (opcional, para el camino “prod”)

## Instalación local (sin Docker)

```bash
cd "Clase III"

# Preferible (si tenés uv):
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt

# Alternativa clásica:
# python -m venv .venv && source .venv/bin/activate
# pip install -r requirements.txt

# Ollama
ollama pull llama3.1

uvicorn app.api:app --reload --port 8000
```

Abrí `http://localhost:8000`.

La DB completa de Clase II ya está en `data/real_estate.db` (default). Seed chico:

```bash
REAL_ESTATE_DB=./data/toy_real_estate.db uvicorn app.api:app --port 8000
```

## Docker Compose

```bash
# Ollama debe estar en el host en :11434
docker compose up --build
```

## Contrato HTTP

| Método | Path | Descripción |
|---|---|---|
| `GET` | `/health` | DB + LLM reachability |
| `GET` | `/meta` | tablas, ejemplos |
| `POST` | `/ask` | `{"question":"..."}` → respuesta + SQL + filas |
| `GET` | `/` | UI mínima |

## Demo en vivo

<https://sql-agent-toy-pwkwf.ondigitalocean.app> — App Platform + DO Serverless Inference
(`llama-4-maverick`). Sin auth: cada pregunta gasta tokens de la cuenta del curso.

```bash
curl -s https://sql-agent-toy-pwkwf.ondigitalocean.app/health | jq
curl -s -X POST https://sql-agent-toy-pwkwf.ondigitalocean.app/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Top 5 propiedades más caras en USD con su dirección"}' | jq
```

## Infraestructura como código (App Platform + LLM)

Ver `infra/README.md`. `llm_backend` elige a dónde habla el agente:

| `llm_backend` | Crea | LLM | Costo |
|---|---|---|---|
| `serverless` (default) | App Platform | DO Serverless Inference, `https://inference.do-ai.run/v1` | ~US$5/mes + tokens |
| `ollama_gpu` | App Platform + GPU Droplet + firewall | Ollama en el GPU, `http://<gpu-ip>:11434/v1` | + ~US$1,57/hora de GPU |

```bash
cd infra
export DIGITALOCEAN_TOKEN=dop_v1_...
export TF_VAR_inference_api_key=...   # Model Access Key de DO (serverless)
terraform init && terraform plan
# terraform apply                     # gasta plata real
```

⚠️ `terraform destroy` al terminar (sobre todo con GPU, que se cobra por hora).

Hay un esbozo AWS en `infra/aws_ecs_fargate.tf.example`.

## CLI agents y MCP

Esta clase no instala un MCP *dentro* del agente SQL; enseña a usar **CLI agents**
(Grok / Claude Code / genérico) y **MCPs de cloud** (DigitalOcean, AWS) para
operar el despliegue. Detalle en la presentación `Clase III.md`.

## Por qué no es “producción real”

- SQLite embebida (no Postgres gestionado)
- Sin auth, rate limit ni multi-tenant
- Sin observabilidad (métricas/trazas)
- Una sola réplica

Sirve para **cerrar el loop lab → contenedor → nube** en una clase.

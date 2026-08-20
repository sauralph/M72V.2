# Clase III — Toy production del bonus de Clase II

Toma la GUI Streamlit del bonus (`Clase II/bonus/`) y la convierte en una
**versión mínima desplegable**: API HTTP + UI estática + Docker + IaC.

| Lab (Clase II bonus) | Toy production (esta carpeta) |
|---|---|
| Streamlit monolito | FastAPI + `static/index.html` |
| Ollama nativo hardcodeado | Cliente OpenAI-compatible (Ollama `/v1` u otro) |
| `python streamlit run` en la laptop | Docker + healthcheck |
| Sin infra | `docker-compose` + Terraform (DO App Platform) |
| DB en carpeta del lab | Copia en `data/real_estate.db` (+ seed toy opcional) |

## Requisitos

- Python 3.11+
- Ollama local **o** una API OpenAI-compatible (`LLM_BASE_URL` + `LLM_API_KEY`)
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

## Infraestructura como código (Ollama en GPU + agente)

Ver `infra/README.md`. En un `terraform apply` crea:

1. **GPU Droplet** con **Ollama** (`llama3.1` por default, puerto `11434`)
2. **App Platform** con el FastAPI, `LLM_BASE_URL=http://<gpu-ip>:11434/v1`

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
# editar github_repo + gpu_region
export DIGITALOCEAN_TOKEN=dop_v1_...
# SSH default: ~/.ssh/id_ed25519_do_lab.pub
#   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_do_lab -N ""
terraform init && terraform plan   # revisá el costo del GPU
# terraform apply                  # solo con cuota/lab y token
```

⚠️ El GPU se cobra por hora mientras exista. `terraform destroy` al terminar.

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

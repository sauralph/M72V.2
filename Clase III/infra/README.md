# Infra · Agente en App Platform + LLM (serverless o GPU)

Dos backends para el LLM, elegidos con `llm_backend`. El agente no cambia:
solo cambian `LLM_BASE_URL`, `LLM_MODEL` y `LLM_API_KEY`.

**A · `serverless` (default, es lo que corre la demo del curso)**

```text
Browser ──HTTPS──► App Platform (FastAPI + SQLite)
                         │
                         │  LLM_BASE_URL=https://inference.do-ai.run/v1
                         ▼
                   DO Serverless Inference (llama-4-maverick)
```

**B · `ollama_gpu` (mismo Ollama que en la laptop, pero en la nube)**

```text
Browser ──HTTPS──► App Platform (FastAPI + SQLite)
                         │
                         │  LLM_BASE_URL=http://<gpu-ip>:11434/v1
                         ▼
                   GPU Droplet (Ollama + llama3.1)
```

| Recurso | Producto DO | Backend | Rol |
|---|---|---|---|
| `digitalocean_app.sql_agent` | **App Platform** | ambos | Toy SQL agent (CPU barato) |
| `digitalocean_droplet.ollama` | **GPU Droplet** | `ollama_gpu` | Sirve el LLM con Ollama |
| `digitalocean_firewall.ollama` | Cloud Firewall | `ollama_gpu` | SSH + `:11434` |
| `digitalocean_ssh_key.lab` | SSH key | `ollama_gpu` | Acceso al GPU |

Demo en vivo del curso: <https://sql-agent-toy-pwkwf.ondigitalocean.app>

## Requisitos

1. `export DIGITALOCEAN_TOKEN=dop_v1_...` (o `doctl auth init` para usar `doctl`).
2. El repo con este monorepo **público** (App Platform lo clona por `repo_clone_url`,
   sin conectar GitHub). Si usás un fork privado, cambiá el bloque `git` por `github`.
3. Según el backend:
   - `serverless`: una **Model Access Key** (consola DO → Inference → Serverless Inference → Model Access Keys).
   - `ollama_gpu`: cuenta con **acceso a GPU Droplets** y una SSH key (abajo).

## Apply · serverless (default)

```bash
cd "Clase III/infra"
cp terraform.tfvars.example terraform.tfvars   # opcional: los defaults ya sirven

export DIGITALOCEAN_TOKEN=dop_v1_...
export TF_VAR_inference_api_key=...            # Model Access Key — nunca en el repo

terraform init
terraform plan        # 1 recurso: digitalocean_app.sql_agent
terraform apply       # ~3–5 min (build del Dockerfile)

curl -s "$(terraform output -raw live_url)/health" | jq
curl -s -X POST "$(terraform output -raw live_url)/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"¿Cuántas propiedades hay por cantidad de dormitorios?"}' | jq
```

La key queda como variable `SECRET` en App Platform (cifrada; la consola no la muestra).

**Modelos**: `inference_model` es un ID del catálogo de DO (ej. `llama-4-maverick`,
`openai-gpt-oss-120b`). Si el ID no existe, `/ask` devuelve `LLM HTTP 404 ... model not found`.
Ojo: el catálogo cambia (p. ej. `llama3.3-70b-instruct` ya no está como serverless).

## Apply · ollama_gpu

### SSH key (si no tenés)

DigitalOcean necesita una clave para crear el droplet. Generá una **solo para el lab**:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_do_lab -N "" -C "m72v2-lab"
```

Terraform la lee sola desde `~/.ssh/id_ed25519_do_lab.pub` (default).  
Para entrar al GPU después:

```bash
ssh -i ~/.ssh/id_ed25519_do_lab root@$(terraform output -raw ollama_public_ip)
```

### Apply

```bash
cd "Clase III/infra"
cp terraform.tfvars.example terraform.tfvars
# editar: llm_backend = "ollama_gpu", gpu_region con stock

export DIGITALOCEAN_TOKEN=dop_v1_...
terraform init
terraform plan        # 4 recursos — ¡mirá el costo del GPU!
terraform apply
```

**Primera boot del GPU:** cloud-init instala Ollama y hace `ollama pull llama3.1`.  
Puede tardar **5–15 minutos**. Después:

```bash
terraform output ollama_smoke_test
# curl -s http://<ip>:11434/api/tags | jq

curl -s "$(terraform output -raw live_url)/health" | jq
```

### Solo Ollama (sin App Platform)

```hcl
llm_backend = "ollama_gpu"
deploy_app  = false
```

Apuntá un agente local:

```bash
export LLM_BASE_URL=$(terraform output -raw llm_base_url)
export LLM_MODEL=llama3.1
export LLM_API_KEY=ollama
uvicorn app.api:app --port 8000
```

## Redeploy después de un push

El bloque `git` no tiene `deploy_on_push`: tras un `git push` hay que redeployar a mano.

```bash
doctl apps create-deployment "$(terraform output -raw app_id)"
# o desde la consola (Actions → Force rebuild) o pidiéndoselo al MCP de DO
```

## Costos (orden de magnitud)

| Pieza | Orden |
|---|---|
| App Platform `apps-s-1vcpu-0.5gb` | ~**US$5 / mes** |
| Serverless `llama-4-maverick` | ~US$0,25 (in) / 0,87 (out) por **millón** de tokens — una pregunta ≈ centavos de centavo |
| GPU RTX 6000 Ada (`gpu-6000adax1-48gb`) — solo `ollama_gpu` | ~**US$1,57 / hora** si está prendida |
| Transfer + storage | menor |

**Destruí al terminar:**

```bash
terraform destroy
```

## Seguridad (límites del toy)

- `serverless`: la key vive como `SECRET` en App Platform; rotala desde la consola si se filtra.
- `ollama_gpu`: Ollama queda en `0.0.0.0:11434` (sin auth nativa) y el firewall abre `:11434`
  a internet para que App Platform pueda llamar. En un lab real: VPC + allowlist,
  reverse proxy con token, o private networking.
- El endpoint `/ask` es público y sin auth: cualquiera con la URL gasta tokens.

## Troubleshooting

| Síntoma | Qué mirar |
|---|---|
| `/ask` → `LLM HTTP 401` | `TF_VAR_inference_api_key` vacía o vencida |
| `/ask` → `LLM HTTP 404 model not found` | `inference_model` no está en el catálogo serverless |
| `/ask` → `localhost:11434 ... refused` | Imagen vieja del agente: redeploy (ver arriba) |
| `size is not available` | Cambiá `gpu_region` / `gpu_size`; revisá stock en la consola DO |
| `/api/tags` connection refused | Esperá cloud-init; `ssh root@IP` y `journalctl -u ollama -f` |
| App `/health` degradado | serverless: key mal; GPU: modelo aún no pulled o firewall bloquea 11434 |
| App no buildea | `repo_clone_url` público y path `Clase III/Dockerfile` correctos |

## No aplica por defecto

Este `terraform apply` **gasta plata real**. No lo corremos desde el repo del curso sin tu token y tu OK explícito.

La demo del curso se creó por MCP/consola (no por este Terraform), con el mismo spec que
genera el backend `serverless`. Para manejarla con Terraform:
`terraform import 'digitalocean_app.sql_agent[0]' <app_id>`.

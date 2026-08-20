# Infra · Ollama en GPU + agente en App Platform

```text
Browser ──HTTPS──► App Platform (FastAPI + SQLite)
                         │
                         │  LLM_BASE_URL=http://<gpu-ip>:11434/v1
                         ▼
                   GPU Droplet (Ollama + llama3.1)
```

| Recurso | Producto DO | Rol |
|---|---|---|
| `digitalocean_droplet.ollama` | **GPU Droplet** | Sirve el LLM con Ollama |
| `digitalocean_firewall.ollama` | Cloud Firewall | SSH + `:11434` |
| `digitalocean_app.sql_agent` | **App Platform** | Toy SQL agent (CPU barato) |

## Requisitos

1. Cuenta DO con **acceso a GPU Droplets** (no todas las cuentas/regiones tienen stock).
2. `export DIGITALOCEAN_TOKEN=dop_v1_...`
3. Repo GitHub con este monorepo (para build del Dockerfile del agente).
4. Una SSH key (se genera en un paso, abajo).

## SSH key (si no tenés)

DigitalOcean necesita una clave para crear el droplet. Generá una **solo para el lab**:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_do_lab -N "" -C "m72v2-lab"
```

Terraform la lee sola desde `~/.ssh/id_ed25519_do_lab.pub` (default).  
Para entrar al GPU después:

```bash
ssh -i ~/.ssh/id_ed25519_do_lab root@$(terraform output -raw ollama_public_ip)
```

## Apply

```bash
cd "Clase III/infra"
cp terraform.tfvars.example terraform.tfvars
# editar: github_repo, gpu_region

export DIGITALOCEAN_TOKEN=dop_v1_...
export TF_VAR_github_repo="tu-usuario/M72V.2"
# SSH: no hace falta export si existe ~/.ssh/id_ed25519_do_lab.pub

terraform init
terraform plan
terraform apply
```

**Primera boot del GPU:** cloud-init instala Ollama y hace `ollama pull llama3.1`.  
Puede tardar **5–15 minutos**. Después:

```bash
terraform output ollama_smoke_test
# curl -s http://<ip>:11434/api/tags | jq

terraform output live_url
curl -s "$(terraform output -raw live_url)/health" | jq
```

## Solo Ollama (sin App Platform)

```hcl
deploy_app = false
```

Apuntá un agente local:

```bash
export LLM_BASE_URL=$(terraform output -raw llm_base_url)
export LLM_MODEL=llama3.1
export LLM_API_KEY=ollama
uvicorn app.api:app --port 8000
```

## Costos (orden de magnitud)

| Pieza | Orden |
|---|---|
| RTX 4000 Ada (`gpu-4000adax1-20gb`) | ~**$0.76 / hora** si está prendida |
| App Platform `basic-xxs` | centavos / hora |
| Transfer + storage | menor |

**Apagá o destruí al terminar la clase:**

```bash
terraform destroy
```

## Seguridad (límites del toy)

- Ollama queda en `0.0.0.0:11434` (sin auth nativa).
- Firewall del toy abre `:11434` a internet para que App Platform pueda llamar.
- En un lab real: VPC + allowlist, o reverse proxy con token, o private networking.

## Troubleshooting

| Síntoma | Qué mirar |
|---|---|
| `size is not available` | Cambiá `gpu_region` / `gpu_size`; revisá stock en la consola DO |
| `/api/tags` connection refused | Esperá cloud-init; `ssh root@IP` y `journalctl -u ollama -f` |
| App `/health` degradado | Modelo aún no pulled; o firewall bloquea 11434 |
| App no buildea | `github_repo` y path `Clase III/Dockerfile` correctos |

## No aplica por defecto

Este `terraform apply` **gasta plata real**. No lo corremos desde el repo del curso sin tu token y tu OK explícito.

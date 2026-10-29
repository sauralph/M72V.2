# Toy production IaC
# Default (llm_backend = "serverless"):
#   App Platform → SQL agent FastAPI → DO Serverless Inference (OpenAI-compatible)
# Alternativa (llm_backend = "ollama_gpu"):
#   App Platform → SQL agent FastAPI → GPU Droplet con Ollama
#
# Costos: App Platform ~US$5/mes + tokens (serverless).
# Con ollama_gpu, el GPU se cobra por hora mientras exista (~$0.76–1.57/hr).
# Always `terraform destroy` when the lab ends.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.49"
    }
  }
}

provider "digitalocean" {
  # export DIGITALOCEAN_TOKEN=dop_v1_...
}

# ── Variables ──────────────────────────────────────────────────────────────

variable "app_name" {
  type        = string
  description = "Base name for App Platform (+ GPU droplet if ollama_gpu)"
  default     = "sql-agent-toy"
}

variable "app_region" {
  type        = string
  description = "App Platform region slug (nyc, ams, sfo, ...)"
  default     = "nyc"
}

variable "app_instance_size" {
  type        = string
  description = "App Platform instance size (apps-s-1vcpu-0.5gb ≈ US$5/mes)"
  default     = "apps-s-1vcpu-0.5gb"
}

variable "repo_clone_url" {
  type        = string
  description = "Public git URL of the repo that contains Clase III/Dockerfile"
  default     = "https://github.com/sauralph/M72V.2.git"
}

variable "repo_branch" {
  type    = string
  default = "main"
}

variable "deploy_app" {
  type        = bool
  description = "Also deploy the FastAPI agent on App Platform"
  default     = true
}

variable "llm_backend" {
  type        = string
  description = "serverless (DO Serverless Inference) | ollama_gpu (GPU Droplet + Ollama)"
  default     = "serverless"

  validation {
    condition     = contains(["serverless", "ollama_gpu"], var.llm_backend)
    error_message = "llm_backend must be \"serverless\" or \"ollama_gpu\"."
  }
}

# ── Serverless inference ──

variable "inference_base_url" {
  type    = string
  default = "https://inference.do-ai.run/v1"
}

variable "inference_model" {
  type        = string
  description = "Model ID from the DO model catalog (serverless)"
  default     = "llama-4-maverick"
}

variable "inference_api_key" {
  type        = string
  description = "DO Model Access Key (export TF_VAR_inference_api_key=...). Never commit it."
  default     = ""
  sensitive   = true
}

# ── Ollama GPU ──

variable "gpu_region" {
  type        = string
  description = "Region with GPU inventory (check console / sizes API; often tor1, nyc2, ams3)"
  default     = "tor1"
}

variable "gpu_size" {
  type        = string
  description = "GPU droplet size slug (https://slugs.do-api.dev/). 4000ada is cheaper but often out of stock."
  default     = "gpu-6000adax1-48gb" # RTX 6000 Ada 48GB — enough for llama3.1
}

variable "gpu_image" {
  type        = string
  description = "OS image for the GPU droplet"
  default     = "ubuntu-22-04-x64"
}

variable "ollama_model" {
  type        = string
  description = "Model to ollama pull on first boot"
  default     = "llama3.1"
}

variable "ssh_public_key" {
  type        = string
  description = "SSH public key contents. Leave empty to read ssh_public_key_path."
  default     = ""
}

variable "ssh_public_key_path" {
  type        = string
  description = "Path to public key file (used when ssh_public_key is empty)"
  default     = "~/.ssh/id_ed25519_do_lab.pub"
}

variable "ssh_allowed_cidrs" {
  type        = list(string)
  description = "Who may SSH into the GPU droplet"
  default     = ["0.0.0.0/0"] # tighten for real use
}

variable "ollama_allowed_cidrs" {
  type        = list(string)
  description = "Who may hit Ollama :11434 (App Platform uses public egress → keep open for toy)"
  default     = ["0.0.0.0/0"]
}

locals {
  use_gpu = var.llm_backend == "ollama_gpu"
}

# ── 1) (Opcional) GPU Droplet + Ollama ─────────────────────────────────────

resource "digitalocean_ssh_key" "lab" {
  count = local.use_gpu ? 1 : 0

  name = "${var.app_name}-gpu"
  public_key = trimspace(
    var.ssh_public_key != "" ? var.ssh_public_key : file(pathexpand(var.ssh_public_key_path))
  )
}

resource "digitalocean_droplet" "ollama" {
  count = local.use_gpu ? 1 : 0

  name     = "${var.app_name}-ollama"
  region   = var.gpu_region
  size     = var.gpu_size
  image    = var.gpu_image
  ssh_keys = [digitalocean_ssh_key.lab[0].id]

  user_data = templatefile("${path.module}/cloud-init-ollama.yaml", {
    ollama_model = var.ollama_model
  })

  tags = ["sql-agent-toy", "ollama", "gpu"]

  # Do not recreate the expensive GPU box when cloud-init text changes.
  lifecycle {
    ignore_changes = [user_data]
  }
}

resource "digitalocean_firewall" "ollama" {
  count = local.use_gpu ? 1 : 0

  name = "${var.app_name}-ollama-fw"

  droplet_ids = [digitalocean_droplet.ollama[0].id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.ssh_allowed_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "11434"
    source_addresses = var.ollama_allowed_cidrs
  }

  inbound_rule {
    protocol         = "icmp"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

locals {
  ollama_base_url = local.use_gpu ? "http://${digitalocean_droplet.ollama[0].ipv4_address}:11434" : null

  # Lo único que cambia entre backends: a dónde habla el agente y con qué key.
  llm_base_url = local.use_gpu ? "${local.ollama_base_url}/v1" : var.inference_base_url
  llm_model    = local.use_gpu ? var.ollama_model : var.inference_model
  llm_api_key  = local.use_gpu ? "ollama" : var.inference_api_key
}

# ── 2) App Platform: SQL agent → LLM ───────────────────────────────────────

resource "digitalocean_app" "sql_agent" {
  count = var.deploy_app ? 1 : 0

  spec {
    name   = var.app_name
    region = var.app_region

    service {
      name               = "api"
      instance_count     = 1
      instance_size_slug = var.app_instance_size
      http_port          = 8000

      # source_dir: app context. dockerfile_path: relative to REPO root (DO quirk).
      source_dir      = "Clase III"
      dockerfile_path = "Clase III/Dockerfile"

      # Repo público: no hace falta conectar GitHub a DO.
      # Sin deploy_on_push → redeploy manual (consola, doctl o MCP).
      git {
        repo_clone_url = var.repo_clone_url
        branch         = var.repo_branch
      }

      env {
        key   = "LLM_BASE_URL"
        value = local.llm_base_url
        scope = "RUN_TIME"
      }
      env {
        key   = "LLM_MODEL"
        value = local.llm_model
        scope = "RUN_TIME"
      }
      env {
        key   = "LLM_API_KEY"
        value = local.llm_api_key
        scope = "RUN_TIME"
        type  = "SECRET"
      }
      env {
        key   = "REAL_ESTATE_DB"
        value = "/data/real_estate.db"
        scope = "RUN_TIME"
      }
      env {
        key   = "LLM_TIMEOUT"
        value = "120"
        scope = "RUN_TIME"
      }
      dynamic "env" {
        for_each = local.use_gpu ? [local.ollama_base_url] : []
        content {
          key   = "OLLAMA_BASE_URL"
          value = env.value
          scope = "RUN_TIME"
        }
      }

      health_check {
        http_path             = "/health"
        initial_delay_seconds = 20
        period_seconds        = 30
        timeout_seconds       = 10
        success_threshold     = 1
        failure_threshold     = 5
      }
    }
  }

  lifecycle {
    precondition {
      condition     = local.use_gpu || var.inference_api_key != ""
      error_message = "llm_backend = \"serverless\" requiere TF_VAR_inference_api_key (Model Access Key de DO)."
    }
  }
}

# ── Outputs ────────────────────────────────────────────────────────────────

output "llm_backend" {
  value = var.llm_backend
}

output "llm_base_url" {
  description = "OpenAI-compatible base for the agent"
  value       = local.llm_base_url
}

output "llm_model" {
  value = local.llm_model
}

output "ollama_public_ip" {
  description = "GPU droplet IPv4 (only ollama_gpu)"
  value       = try(digitalocean_droplet.ollama[0].ipv4_address, null)
}

output "ollama_smoke_test" {
  description = "Run after bootstrap finishes (~5–15 min first boot)"
  value       = local.use_gpu ? "curl -s ${local.ollama_base_url}/api/tags | jq" : null
}

output "live_url" {
  description = "Public URL of the SQL agent (if deploy_app=true)"
  value       = try(digitalocean_app.sql_agent[0].live_url, null)
}

output "app_id" {
  value = try(digitalocean_app.sql_agent[0].id, null)
}

output "cost_reminder" {
  value = local.use_gpu ? "GPU droplet bills hourly while running. terraform destroy when done." : "App Platform ~US$5/mes + tokens. terraform destroy when done."
}

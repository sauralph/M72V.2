# Toy production IaC
# 1) GPU Droplet  → Ollama (OpenAI-compatible on :11434/v1)
# 2) App Platform → SQL agent FastAPI, wired to that Ollama
#
# Cost warning: GPU droplets are billed hourly while running (~$0.76+/hr for RTX 4000 Ada).
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
  description = "Base name for App Platform + GPU droplet"
  default     = "sql-agent-toy"
}

variable "app_region" {
  type        = string
  description = "App Platform region slug (nyc, ams, sfo, ...)"
  default     = "nyc"
}

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

variable "github_repo" {
  type        = string
  description = "owner/repo that contains Clase III/Dockerfile"
}

variable "github_branch" {
  type    = string
  default = "main"
}

variable "deploy_on_push" {
  type    = bool
  default = true
}

variable "deploy_app" {
  type        = bool
  description = "Also deploy the FastAPI agent on App Platform"
  default     = true
}

# ── SSH key ───────────────────────────────────────────────────────────────

locals {
  ssh_public_key = trimspace(
    var.ssh_public_key != "" ? var.ssh_public_key : file(pathexpand(var.ssh_public_key_path))
  )
}

resource "digitalocean_ssh_key" "lab" {
  name       = "${var.app_name}-gpu"
  public_key = local.ssh_public_key
}

# ── 1) GPU Droplet + Ollama ────────────────────────────────────────────────

resource "digitalocean_droplet" "ollama" {
  name     = "${var.app_name}-ollama"
  region   = var.gpu_region
  size     = var.gpu_size
  image    = var.gpu_image
  ssh_keys = [digitalocean_ssh_key.lab.id]

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
  name = "${var.app_name}-ollama-fw"

  droplet_ids = [digitalocean_droplet.ollama.id]

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
  ollama_base_url = "http://${digitalocean_droplet.ollama.ipv4_address}:11434"
  llm_base_url    = "${local.ollama_base_url}/v1"
}

# ── 2) App Platform: SQL agent → Ollama GPU ────────────────────────────────

resource "digitalocean_app" "sql_agent" {
  count = var.deploy_app ? 1 : 0

  spec {
    name   = var.app_name
    region = var.app_region

    service {
      name               = "api"
      instance_count     = 1
      instance_size_slug = "basic-xxs"
      http_port          = 8000

      # source_dir: app context. dockerfile_path: relative to REPO root (DO quirk).
      source_dir      = "Clase III"
      dockerfile_path = "Clase III/Dockerfile"

      github {
        repo           = var.github_repo
        branch         = var.github_branch
        deploy_on_push = var.deploy_on_push
      }

      # Wire agent to the GPU Ollama (OpenAI-compatible).
      env {
        key   = "LLM_BASE_URL"
        value = local.llm_base_url
        scope = "RUN_TIME"
      }
      env {
        key   = "OLLAMA_BASE_URL"
        value = local.ollama_base_url
        scope = "RUN_TIME"
      }
      env {
        key   = "LLM_MODEL"
        value = var.ollama_model
        scope = "RUN_TIME"
      }
      env {
        key   = "OLLAMA_LLM_MODEL"
        value = var.ollama_model
        scope = "RUN_TIME"
      }
      env {
        key   = "LLM_API_KEY"
        value = "ollama"
        scope = "RUN_TIME"
      }
      env {
        key   = "REAL_ESTATE_DB"
        value = "/data/real_estate.db"
        scope = "RUN_TIME"
      }
      env {
        key   = "LLM_TIMEOUT"
        value = "180"
        scope = "RUN_TIME"
      }

      health_check {
        http_path             = "/health"
        initial_delay_seconds = 30
        period_seconds        = 30
        timeout_seconds       = 5
        success_threshold     = 1
        failure_threshold     = 5
      }
    }
  }

  depends_on = [digitalocean_droplet.ollama]
}

# ── Outputs ────────────────────────────────────────────────────────────────

output "ollama_public_ip" {
  description = "GPU droplet IPv4"
  value       = digitalocean_droplet.ollama.ipv4_address
}

output "ollama_base_url" {
  description = "Native Ollama URL"
  value       = local.ollama_base_url
}

output "llm_base_url" {
  description = "OpenAI-compatible base for the agent"
  value       = local.llm_base_url
}

output "ollama_smoke_test" {
  description = "Run after bootstrap finishes (~5–15 min first boot)"
  value       = "curl -s ${local.ollama_base_url}/api/tags | jq"
}

output "live_url" {
  description = "Public URL of the SQL agent (if deploy_app=true)"
  value       = try(digitalocean_app.sql_agent[0].live_url, null)
}

output "app_id" {
  value = try(digitalocean_app.sql_agent[0].id, null)
}

output "cost_reminder" {
  value = "GPU droplet bills hourly while running. terraform destroy when done."
}

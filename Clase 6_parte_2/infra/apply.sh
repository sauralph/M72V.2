#!/usr/bin/env bash
# Always run Terraform from this directory (the folder that contains main.tf).
set -euo pipefail
cd "$(dirname "$0")"
export PATH="${HOME}/.local/bin:${PATH}"

if [[ -z "${DIGITALOCEAN_TOKEN:-}" ]]; then
  echo "error: export DIGITALOCEAN_TOKEN=dop_v1_... first" >&2
  exit 1
fi

if [[ ! -f "${HOME}/.ssh/id_ed25519_do_lab.pub" && -z "${TF_VAR_ssh_public_key:-}" ]]; then
  echo "error: missing ~/.ssh/id_ed25519_do_lab.pub" >&2
  echo "  ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_do_lab -N ''" >&2
  exit 1
fi

terraform init -input=false
terraform apply "$@"

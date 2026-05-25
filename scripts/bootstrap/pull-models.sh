#!/usr/bin/env bash
# Pull every Ollama model defined in .env's OLLAMA_MODELS list.
set -euo pipefail

# shellcheck disable=SC1091
# shellcheck source=/dev/null
source .env
models=${OLLAMA_MODELS:-"qwen2.5-coder:7b llama3.1:8b nomic-embed-text"}

for m in $models; do
  echo ">> pulling $m"
  docker compose exec -T ollama ollama pull "$m"
done

echo "models present:"
docker compose exec -T ollama ollama list

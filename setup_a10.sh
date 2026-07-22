#!/usr/bin/env bash
# One-time setup on a Lambda (or any Ubuntu + NVIDIA GPU) instance:
#   bash setup_a10.sh
# Installs Ollama and pre-pulls the 5 test models + the judge (~12GB total).
set -euo pipefail

if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Ollama runs as a systemd service after install; give it a moment
sleep 3

for model in qwen2.5:0.5b llama3.2:1b gemma3:1b qwen2.5:1.5b smollm2:1.7b qwen2.5:14b; do
    echo "=== pulling $model ==="
    ollama pull "$model"
done

echo
echo "Done. Verify with:  curl http://localhost:11434/v1/models"
echo "Then run the benchmark (on this box, or from your laptop via:"
echo "  ssh -L 11434:localhost:11434 ubuntu@<this-machine-ip> )"

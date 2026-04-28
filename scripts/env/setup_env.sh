#!/usr/bin/env bash
# Setup environment for DHAv6 + baselines evaluation
# Requires: conda, CUDA, Docker
set -euo pipefail

ENV_NAME="${ENV_NAME:-dha_env}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"

echo "=== Creating conda environment: $ENV_NAME ==="
conda create -n "$ENV_NAME" python="$PYTHON_VERSION" -y
eval "$(conda shell.bash hook 2>/dev/null)"
conda activate "$ENV_NAME"

echo "=== Installing harbor (eval framework) ==="
pip install 'harbor>=0.1.44'

echo "=== Installing SGLang (model serving) ==="
pip install 'sglang[all]>=0.4.5'

echo "=== Installing DHAv6 dependencies ==="
pip install 'litellm>=1.60,<1.82.7' 'tenacity>=8.0' 'tiktoken'

echo "=== Installing baseline agent dependencies ==="
# These are installed automatically by harbor on first use, but pre-installing
# avoids timeouts during evaluation runs.
pip install 'openai>=1.0' 'anthropic>=0.30'

echo "=== Verifying installation ==="
python -c "import harbor; print(f'harbor {harbor.__version__}')"
python -c "import litellm; print(f'litellm {litellm.__version__}')"
python -c "import sglang; print(f'sglang OK')"

echo ""
echo "=== Setup complete ==="
echo "Activate with: conda activate $ENV_NAME"
echo ""
echo "Next steps:"
echo "  1. Start SGLang server:  bash scripts/serve/serve_model.sh <model_path> <port>"
echo "  2. Run baselines:        bash scripts/baselines/run_baselines.sh <port>"
echo "  3. Run DHAv6:            bash scripts/dhav6/run_dhav6.sh <port>"

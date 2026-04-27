#!/usr/bin/env bash
# Wire DHAv6 into an existing harbor installation.
#
# Usage: ./apply_patch.sh
#
# This symlinks the dhav6/ directory into harbor's agent tree so that
# --agent-import-path dhav6_agent:DHAv6Agent works.
# No patch to harbor source is needed — harbor supports --agent-import-path
# for external agents. This script is a convenience for PYTHONPATH setup.
set -euo pipefail

DHAV6_REPO=$(cd "$(dirname "$0")/.." && pwd)

echo "DHAv6 repo at: $DHAV6_REPO"
echo ""
echo "To use DHAv6 with harbor, add the dhav6/ directory to PYTHONPATH:"
echo ""
echo "  export PYTHONPATH=$DHAV6_REPO/dhav6:\$PYTHONPATH"
echo ""
echo "Then run with:"
echo "  # Terminal-Bench 2.0"
echo "  harbor run --agent-import-path dhav6_agent:DHAv6Agent \\"
echo "    -m openai/<model> -d terminal-bench@2.0 ..."
echo ""
echo "  # SWE-bench Verified"
echo "  harbor run --agent-import-path dhav6_miniswe_agent:DHAv6MiniSweAgent \\"
echo "    -m openai/<model> -d swebench-verified ..."
echo ""
echo "Or use the provided scripts in scripts/dhav6/."

#!/usr/bin/env bash
# FastPOS Launch Script
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ -f "./venv/bin/python" ]; then
    PYTHON_EXEC="./venv/bin/python"
else
    PYTHON_EXEC="python3"
fi

echo "🚀 Starting FastPOS Premium Desktop Terminal..."
"$PYTHON_EXEC" main.py

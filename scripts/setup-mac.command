#!/bin/zsh
set -eu
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME_DIR="$HOME/Library/Application Support/KAISTLogin/runtime"
python3 -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
python3 -m venv "$RUNTIME_DIR"
"$RUNTIME_DIR/bin/python" -m pip install "$PROJECT_DIR"
"$RUNTIME_DIR/bin/python" -m playwright install chromium
"$RUNTIME_DIR/bin/python" -m kaist_login setup
"$RUNTIME_DIR/bin/python" -m kaist_login mcp-config
echo '설치 완료. README.md의 Gmail 연결 및 최초 화면 등록을 진행하세요.'
read -r '?Enter를 누르면 닫힙니다. '

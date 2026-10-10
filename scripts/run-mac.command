#!/bin/zsh
set -eu
PYTHON="$HOME/Library/Application Support/KAISTLogin/runtime/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo '먼저 setup-mac.command를 실행하세요.'
  exit 1
fi
if (( $# == 0 )); then
  "$PYTHON" -m kaist_login setup
else
  "$PYTHON" -m kaist_login "$@"
fi

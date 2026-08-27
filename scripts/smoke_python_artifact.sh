#!/usr/bin/env bash
set -euo pipefail

wheel=${1:?usage: smoke_python_artifact.sh PATH_TO_WHEEL}
wheel=$(cd "$(dirname "$wheel")" && pwd)/$(basename "$wheel")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

python -m venv "$work/venv"
"$work/venv/bin/python" -m pip install --disable-pip-version-check "$wheel"
(
  cd "$work"
  PYTHONPATH= "$work/venv/bin/python" - <<'PY'
from robotscenter import AsyncRobotsCenterClient, Realtime, RobotsCenterClient

assert RobotsCenterClient.__name__ == "RobotsCenterClient"
assert AsyncRobotsCenterClient.__name__ == "AsyncRobotsCenterClient"
assert Realtime.__name__ == "Realtime"
PY
)

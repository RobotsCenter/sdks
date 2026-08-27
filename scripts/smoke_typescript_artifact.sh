#!/usr/bin/env bash
set -euo pipefail

archive=${1:?usage: smoke_typescript_artifact.sh PATH_TO_TGZ}
archive=$(cd "$(dirname "$archive")" && pwd)/$(basename "$archive")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

cd "$work"
npm init --yes >/dev/null
npm install --ignore-scripts "$archive"
node --input-type=module - <<'JS'
import {Realtime, RobotsCenterClient} from "@robotscenter/sdk";
if (typeof Realtime !== "function" || typeof RobotsCenterClient !== "function") process.exit(1);
JS
node - <<'JS'
const {Realtime, RobotsCenterClient} = require("@robotscenter/sdk");
if (typeof Realtime !== "function" || typeof RobotsCenterClient !== "function") process.exit(1);
JS

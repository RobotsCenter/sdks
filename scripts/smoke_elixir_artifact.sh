#!/usr/bin/env bash
set -euo pipefail

archive=${1:?usage: smoke_elixir_artifact.sh PATH_TO_HEX_TAR}
archive=$(cd "$(dirname "$archive")" && pwd)/$(basename "$archive")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

mkdir -p "$work/package" "$work/consumer/lib"
tar -xOf "$archive" contents.tar.gz | tar -xz -C "$work/package"
cat >"$work/consumer/mix.exs" <<'ELIXIR'
defmodule RobotsCenterArtifactSmoke.MixProject do
  use Mix.Project

  def project do
    [
      app: :robots_center_artifact_smoke,
      version: "0.0.0",
      elixir: "~> 1.18",
      deps: [{:robots_center, path: "../package"}]
    ]
  end
end
ELIXIR
cat >"$work/consumer/lib/smoke.ex" <<'ELIXIR'
defmodule RobotsCenterArtifactSmoke do
  def run do
    %RobotsCenter.Client{} = RobotsCenter.Client.new(token: "artifact-smoke")
    {:module, RobotsCenter.Realtime} = Code.ensure_loaded(RobotsCenter.Realtime)
    :ok
  end
end
ELIXIR
(
  cd "$work/consumer"
  mix deps.get
  mix compile --warnings-as-errors
  mix run -e 'unless RobotsCenterArtifactSmoke.run() == :ok, do: System.halt(1)'
)

# AGENTS.md

Instructions for AI assistants working in `robotscenter-sdks`.

## Overview

Official SDKs for Robots Center cross-agent communication (`robotscenter.net`).

## Monorepo Layout (`packages/`)

- `packages/python`: Python client (`robotscenter`, Python 3.11–3.14)
- `packages/typescript`: TypeScript / Node.js client (`@robotscenter/sdk`, Node 22/24)
- `packages/elixir`: Elixir client (`robots_center`, Elixir 1.18, OTP 27/28)
- `contracts/`: Protocol specifications and shared schema definitions

## Verification

Each language SDK has its own test suite:
- Python: `pytest` / `ruff check` / `mypy`
- TypeScript: `pnpm test` / `pnpm typecheck`
- Elixir: `mix test`

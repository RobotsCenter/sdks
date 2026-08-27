# API contract

`openapi.json` is a reviewed snapshot of the Robots Center OpenAPI 3.1 document
served at `/api/v1/openapi/agent-communication.json`. SDK builds use the
committed contract and never depend on an unselected live deployment.

`realtime.json` is the corresponding machine-readable Phoenix v2 agent-channel
manifest, including client/server events, scopes, payload limits, heartbeat
intervals, retry policy, and subscription replay rules.

`python scripts/validate_contracts.py` performs the offline validation used on
every pull request. A publishing release must also supply a deployment URL;
`python scripts/check_contract_sync.py --base-url https://staging.example`
compares both committed documents byte-for-byte at the JSON data-model level
with that deployment's public contract endpoints. This makes conformance an
explicit release decision without making ordinary pull requests depend on a
live service.

Release evidence contains SHA-256 hashes for both contract files and every
built package. The evidence is tied to the immutable commit peeled from a
GitHub-verified signed component tag.

`source.json` records the reviewed AgentOps source commit, public endpoint, and
SHA-256 digest for each generated snapshot. Offline validation fails if a
snapshot changes without updating this provenance record.

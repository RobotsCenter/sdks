# API contract

`openapi.json` is a reviewed snapshot of the Robots Center OpenAPI 3.1 document
served at `/api/v1/openapi.json`. SDK releases are tested against this committed
contract rather than generating code directly from a live deployment.

`realtime.json` is the corresponding machine-readable Phoenix v2 agent-channel
manifest, including client/server events, scopes, payload limits, heartbeat
intervals, retry policy, and subscription replay rules.

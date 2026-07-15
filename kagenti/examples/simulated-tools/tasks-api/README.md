# Tasks API — Simulated Tool Worked Example

A minimal to-do **Tasks API** (`openapi.json`) used to demonstrate Kagenti's
simulated-tool path: Kagenti stands up an MCP server that simulates this REST API
from the spec alone — no real backend required.

- `openapi.json` — the OpenAPI 3.1 spec (full CRUD: list/create/read/update/delete).
- `db.json` — a small seed dataset used by `seed.sh` and as an example re-seed payload.
- `seed.sh` — one-command demo seeding: creates the simulated tool from `openapi.json`
  in a target namespace and waits until it is Ready.

See [docs/new-simulated-tool.md](../../../../docs/new-simulated-tool.md) for the full
walkthrough, prerequisites (LLM API key Secret, egress allow-listing), and lifecycle.

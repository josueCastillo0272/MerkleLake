# API Contracts

**Purpose:** How clients talk to MerkleLake. This file names each endpoint, its intent, auth requirements, and the *fields by name* that flow through requests/responses. Exact JSON schemas and status codes TBD.

## Table of contents

- [Principles](#principles)
- [Auth & Tenancy](#auth--tenancy)
- [Endpoints](#endpoints)
  - [POST /v1/logs — Ingest a batch](#post-v1logs--ingest-a-batch)
  - [POST /v1/search — Query logs](#post-v1search--query-logs)
  - [GET /v1/proof — Get a Merkle proof](#get-v1proof--get-a-merkle-proof)
  - [GET /v1/checkpoint — Latest chain tip](#get-v1checkpoint--latest-chain-tip)
- [Objects & Field Names](#objects--field-names)
- [Notes on Pagination & Proof Delivery](#notes-on-pagination--proof-delivery)
- [Integrity & Trust Model (client view)](#integrity--trust-model-client-view)

---

## Principles

- **Tamper-evidence by default:** every stored event is sealed into a Merkle-rooted block linked to its predecessor.
- **Searchable at scale:** metadata is indexed in Elasticsearch; raw events live in immutable object storage.
- **Verifiable results:** clients can request or receive proofs to independently verify hits.
- **Multi-tenant isolation:** all operations scoped by `tenant_id`.

---

## Auth & Tenancy

- **Clients** authenticate with **JWT** (roles: `ingest:write`, `search:read`, `proof:read`).
- **Node↔node** communication (if used) is **mTLS** (mutual authentication).
- All endpoints are **tenant-scoped** via `tenant_id` in the payload or claims.

---

## Endpoints

### POST /v1/logs — Ingest a batch

**Intent:** Submit a batch of events for a tenant. The service batches, seals, stores, and indexes them.

- **Auth:** JWT with `ingest:write`
- **Request (fields by name):**
  - `tenant_id`
  - `events[]` (each: `timestamp`, `attrs`, `message`)
  - `idempotency_key` (optional)
- **Response (fields by name):**
  - `block_id`
  - `root_hash`
  - `ts_range` (e.g., block start/end timestamps)
  - `accepted_count`

> Notes:
    - Batching policy is size/time based (e.g., ~10k events or ~2s).  
    - Blocks are immutable once sealed.

---

### POST /v1/search — Query logs

**Intent:** Find events matching filters/time windows; returns hits and a paging token.

- **Auth:** JWT with `search:read`
- **Request (fields by name):**
  - `tenant_id`
  - `query` (text/filter expression)
  - `time_range`
  - `page` or `page_size` (or `cursor`)
- **Response (fields by name):**
  - `hits[]`
    - `event_meta` (e.g., `timestamp`, `attrs`, `message`)
    - `block_id`
    - `leaf_idx`
  - `next_page_token` (if more results)

> Proofs may be **embedded** per hit or fetched later via `/v1/proof` to keep responses small. See [Notes on Proof Delivery](#notes-on-pagination--proof-delivery).

---

### GET /v1/proof — Get a Merkle proof

**Intent:** Return the minimal Merkle path to recompute a block’s `root_hash` for a specific event.

- **Auth:** JWT with `proof:read`
- **Query params:**
  - `block_id`
  - `leaf_idx`
- **Response (fields by name):**
  - `path[]` (each: `sibling_hash`, `side`)
  - `block_header` (contains `block_id`, `tenant_id`, `ts_start`, `ts_end`, `root_hash`, `prev_block_hash`, `link_hash`)
  - `root_hash`

> Client verification: hash the event, fold in each `path` step (left/right order via `side`), compare to `root_hash`; then follow `block_header.prev_block_hash` (or `link_hash`) as desired.

---

### GET /v1/checkpoint — Latest chain tip

**Intent:** Publish the newest sealed block so clients can anchor verification to a public reference.

- **Auth:** public read
- **Response (fields by name):**
  - `block_id`
  - `link_hash`
  - `prev_link_hash`
  - `published_at`

> Clients may walk backward from `block_id` using `prev_link_hash` to audit continuity.

---

## Objects & Field Names

### Event (ingest/search contexts)

- `tenant_id`
- `timestamp` (server will record `ingest_ts` as well)
- `attrs` (key/value tags)
- `message` (string)

### Block (storage artifact)

- `events.jsonl` (raw events)
- `block.json` (**BlockHeader**)

### BlockHeader

- `block_id`
- `tenant_id`
- `ts_start`, `ts_end`
- `root_hash`
- `prev_block_hash`
- `link_hash` (digest of the header used for public anchoring)

### Hit (search response element)

- `event_meta`
- `block_id`
- `leaf_idx`

### ProofBundle (proof response)

- `path[]` (sequence of `sibling_hash`, `side`)
- `block_header`
- `root_hash`

### Checkpoint

- `block_id`
- `link_hash`
- `prev_link_hash`
- `published_at`

---

## Notes on Pagination & Proof Delivery

- **Pagination:** use `page/page_size` or a **cursor** (`next_page_token`) to stream large result sets.
- **Proofs:** for large pages, return hits first (fast) and allow clients to fetch proofs only for the hits they need to verify. For smaller pages or admin views, proofs can be embedded inline to reduce round-trips.

---

## Integrity & Trust Model (client view)

1. **Inclusion:** `/v1/proof` provides a path proving an event is in a block (recompute `root_hash`).
2. **Immutability:** blocks are immutable; any post-hoc change breaks the Merkle root.
3. **Global anchoring:** `/v1/checkpoint` publishes the latest link; walking `prev_link_hash` detects history rewrites.
4. **Search honesty:** the server can’t forge events without breaking verification. Withholding is mitigated by paging and optional proof-per-hit strategies.

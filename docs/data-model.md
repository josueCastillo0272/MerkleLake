# Data Model

This document defines the **nouns** in MerkleLake—what objects exist, what they mean, and how they relate.

## Table of Contents

- [Overview](#overview)
- [Objects](#objects)
  - [Event](#event)
  - [Block](#block)
  - [BlockHeader](#blockheader)
  - [ProofBundle](#proofbundle)
  - [Checkpoint](#checkpoint)
- [Identifiers & Layout](#identifiers--layout)
- [Search Index (Elasticsearch) Fields](#search-index-elasticsearch-fields)
- [Storage Artifacts](#storage-artifacts)
- [Invariants](#invariants)
- [Tiny End-to-End Example](#example)

---

## Overview

MerkleLake ingests **events**, batches them into **blocks**, seals each block with a **Merkle root** and links it to the previous block (a **hash chain**). Search returns hits plus the location of each event inside its block; clients can fetch a **ProofBundle** to verify inclusion and chain continuity against a published **Checkpoint**.

---

## Objects

### Event

A single log entry provided by clients.

- **Fields (names only)**
  - `tenant_id`
  - `timestamp` (client-provided event time)
  - `ingest_ts` (server-recorded arrival time)
  - `attrs` (key/value tags, e.g., `service`, `region`, `level`, etc.)
  - `message` (string; free-text)

- **Notes**
  - Hash input for Merkle leaves is a stable encoding of the event.
  - Server MAY normalize or add metadata (e.g., request id) before hashing.

---

### Block

A batch of events sealed together and written immutably.

- **Composed of**
  - `events.jsonl` — newline-delimited raw events (immutable)
  - `block.json` — a **BlockHeader** (see below)

- **Batch policy**
  - Time/size based (e.g., **max(10k events, 2s)**).

---

### BlockHeader

Metadata and cryptographic material describing a block.

- **Fields**
  - `block_id` — unique identifier for this block
  - `tenant_id`
  - `ts_start`, `ts_end` — min/max event timestamps in this block
  - `root_hash` — Merkle root over leaf hashes
  - `prev_block_hash` — hash of previous block header (chain link)
  - `link_hash` — digest over this header (anchor used by checkpoints)

- **Notes**
  - Any mutation to `events.jsonl` or header fields changes `root_hash` or `link_hash`, breaking the chain.

---

### ProofBundle

Everything a client needs to verify that a specific event is included in a block and to anchor that block in the chain.

- **Fields**
  - `leaf_idx` — zero-based index of the event in the block
  - `path[]` — sequence of `(sibling_hash, side)` up the Merkle tree
  - `block_header` — the **BlockHeader** for this block
  - `root_hash` — expected Merkle root (redundant convenience)

- **Client verification (conceptual)**
  1. Hash the event bytes → `leaf`.
  2. Fold `leaf` with each `(sibling_hash, side)` in order to recompute `root_hash`.
  3. Compare to `root_hash` from the header; match ⇒ inclusion proven.
  4. Optionally walk `prev_block_hash` and/or compare `link_hash` with **Checkpoint**.

---

### Checkpoint

A public “tip” of the chain for external anchoring.

- **Fields**
  - `block_id`
  - `link_hash`
  - `prev_link_hash`
  - `published_at`

- **Notes**
  - Published at a fixed cadence (e.g., every 60s). Clients can walk back via `prev_link_hash` to audit continuity.

---

## Identifiers & Layout

- **`block_id` format**
  - `<tenant>-<ISO8601-utc-start>-<counter>`
  - Example: `acme-co-2025-11-09T22:15:00Z-0007`
  - Properties: human-readable, sortable, supports multiple blocks per window.

- **`leaf_idx`**
  - Zero-based index into the block’s leaf array: `0 .. (n-1)`.

- **Object storage path (S3/MinIO)**

<tenant_id>/< YYYY >/< MM >/< DD >/<block_id>/{events.jsonl, block.json}

acme-co/2025/11/09/acme-co-2025-11-09T22:15:00Z-0007/events.jsonl

acme-co/2025/11/09/acme-co-2025-11-09T22:15:00Z-0007/block.json

---

## Search Index (Elasticsearch) Fields

Used to **find** events quickly; not the source of truth.

- `tenant_id : keyword`
- `@timestamp : date` (primary time for queries; typically equals `timestamp` or `ingest_ts`, per decision)
- `message : text` + `message.raw : keyword`
- `attrs.* : keyword/text` (dynamic mapping for tags)
- `block_id : keyword`
- `leaf_idx : integer`
- `root_hash : keyword` (stored for quick validation)

**Note:** Full raw events live in object storage; ES stores searchable metadata and pointers (`block_id`, `leaf_idx`).

---

## Storage Artifacts

- **`events.jsonl`**
- Immutable, newline-delimited event records for the block.
- **`block.json`**
- Serialized **BlockHeader**.
- **Checkpoint object** (public)
- Latest `link_hash`, `block_id`, `prev_link_hash`, `published_at` at a known path (e.g., `checkpoints/latest.json`).

---

## Invariants

- **Immutability:** Once sealed, a block’s `events.jsonl` and `block.json` MUST NEVER change.
- **Tamper-evidence:** Any change to a block’s contents or header MUST change `root_hash` and thus the chain.
- **Deterministic hashing:** Event → leaf hash encoding MUST be stable across time and nodes.
- **Tenant isolation:** All identifiers and paths are tenant-scoped; cross-tenant access is forbidden.
- **Proof minimality:** `path[]` is O(log n) in block size.
- **Checkpoint monotonicity:** Newly published checkpoints MUST reference the current chain tip and maintain backward continuity.

---

## Example

**1) Ingest** two events for `acme-co` around `22:15:01Z`.  
**2) Block** is sealed:

- `block_id`: `acme-co-2025-11-09T22:15:00Z-0007`
- `ts_start`: `22:15:00Z`, `ts_end`: `22:15:02Z`
- `root_hash`: `…6f3c…`
- `prev_block_hash`: `…c0ff…`
- `link_hash`: `…2f9b…`

**3) Search** returns a hit with:

- `event_meta` + `block_id` = `acme-co-2025-11-09T22:15:00Z-0007`

- `leaf_idx` = `1`

**4) ProofBundle** for `(block_id, leaf_idx=1)` includes:

- `path[]`: three `(sibling_hash, side)` steps
- `block_header`: the header above
- `root_hash`: `…6f3c…`

**5) Checkpoint** at `23:00:00Z` publishes:

- `block_id`: `acme-co-2025-11-09T22:59:00Z-0019`
- `link_hash`: `…f7b0…`
- `prev_link_hash`: `…2f9b…` (chained)

Clients can verify inclusion and walk continuity from the checkpoint backwards.

---

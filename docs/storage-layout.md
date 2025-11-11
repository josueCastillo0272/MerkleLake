# Storage Layout

This document describes how MerkleLake organizes, names, and protects all log data stored in object storage (S3/MinIO).  
All content here is **prose only**—no code or schemas—and forms the reference for later implementation.

---

## Buckets and Responsibilities

| Bucket Name | Purpose | Notes |
|--------------|----------|-------|
| **`merklelake-blocks`** | Stores small JSON headers for each sealed block (`block.json`) containing block metadata such as root hash, timestamps, and chain link fields. | Private, append-only. |
| **`merklelake-events`** | Stores raw event batches (`events.jsonl`) corresponding to the same block IDs in `merklelake-blocks`. Each file contains all events for one batch. | Private, append-only, large objects. |
| **`merklelake-public`** | Exposes public checkpoint files representing the latest chain tip for each tenant. | Public read; objects immutable. |

**Rationale:**  
Buckets are separated so each can follow its own lifecycle and access policy.  
`merklelake-public` is intentionally read-only so external clients can verify integrity independently.

---

## Object Naming and Partitioning

### Prefixing Convention

All objects are nested by **tenant and calendar date** to keep listings bounded and enable lifecycle rules.

{bucket}/{tenant_id}/{ yyyy }/{ mm }/{ dd }/...
merklelake-blocks/{tenant}/{ yyyy }/{ mm }/{ dd }/{block_id}/block.json
merklelake-events/{tenant}/{ yyyy }/{ mm }/{ dd }/{block_id}/events.jsonl

### Why This Layout

- **Predictable paths:** deterministic from tenant + date + block ID.  
  Retrieval is constant-time—no global scans.  
- **Partitioned by day:** simplifies cleanup, lifecycle transitions, and analytics.

---

## Immutability and Versioning Policy

- All objects are **write-once**. Never overwrite existing data.  
  New data → new block.
- **Bucket versioning enabled** for defense-in-depth; overwritten or deleted objects retain history.  
- **Server-side encryption** is optional and can be enabled without affecting verification  
  (hashes are computed pre-encryption).
- **Lifecycle:**  
  - `events` and `blocks` retained long-term.  
  - Older objects can transition to infrequent-access tiers.  
  - `public` checkpoints remain permanently available for audit.

---

## Block Sizing Reminders

Blocks close based on **size or time**—whichever comes first.

- **Maximum events per block:** *N* (see `docs/decisions.md`, e.g., 10 000).  
- **Maximum time window:** Δ seconds (e.g., 2 s).  
- Each `block.json` header records:
  - `ts_start`
  - `ts_end`
  - `count`
  - `root_hash`
  - `prev_block_hash`

This ensures deterministic batching and replayable verification.

---

## Traceability Invariant

For every indexed search hit `(tenant, block_id, leaf_idx)` returned by Elasticsearch,  
the system **must** be able to perform the following deterministic trace:

1. **Fetch** the corresponding `events.jsonl` file from object storage for that `block_id`.  
2. **Locate** line number `leaf_idx` (the event’s position within the block).  
3. **Re-compute** the hash of that event and walk its Merkle path up to the stored root hash.  
4. **Compare** the computed root with the one recorded in `block.json`.  

If and only if they match, the event is proven authentic and untampered.

> This invariant is the core integrity guarantee of MerkleLake.  
> Every design decision—index schema, storage key, and proof format—must preserve this traceability property.

---

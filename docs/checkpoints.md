# Checkpoints & Anchoring

This document describes how MerkleLake publishes and verifies **chain checkpoints** (the latest block link per tenant) so clients can independently reason about log integrity over time.

---

## What is a checkpoint?

A **checkpoint** is a small JSON document that records the **latest chain tip** for a tenant.  
It carries, at minimum, the following fields (names only):

- `block_id` — identifier of the newest sealed block for the tenant
- `link_hash` — hash of the block header (the chain’s tip)
- `prev_link_hash` — the previous tip’s `link_hash` (forms a linear chain)
- `published_at` — time the checkpoint was published

A checkpoint is **not** a block; it’s a public announcement of which block is the current tip.

---

## Where is it published?

Public bucket (readable by anyone):

- **Latest pointer (mutable, monotonic):**  
  `merklelake-public/checkpoints/{ tenant }/latest.json`

- **Historical snapshots (append-only):**  
  `merklelake-public/checkpoints/{ tenant }/history/{ yyyy }/{ mm }/{ dd }/{ timestamp }.json`

Notes:

- `latest.json` always reflects the newest published tip for `{ tenant }`.
- A copy of each new `latest` is also written to the **history** path so the evolution of tips is auditable.
- Objects in the public bucket are **immutable** once written (history never changes).

---

## Cadence & guarantees

- **Publish cadence:** every **60 seconds** (see `docs/decisions.md`).
- **Monotonicity:** each new `latest.json` must set
  - `prev_link_hash == (prior latest).link_hash`
  - This ensures a linear, append-only chain of tips.
- **Client expectation:** clients cache the most recent `latest.json` they’ve seen and require **non-decreasing** tips across sessions (i.e., no going backwards).

---

## Client verification (high-level)

When a client receives a search result and proof bundle:

1. **Verify the Merkle proof** from the event’s leaf to the block’s `root_hash` in the block header.
2. **Bind the block header to the chain** by hashing it to obtain `link_hash`.
3. **Fetch `latest.json`** for the tenant and/or consult **history** to ensure this block’s `link_hash` appears **on or before** the current tip through a sequence of `prev_link_hash` links.
4. **Accept** only if the block’s `link_hash` is consistent with the published (monotonic) chain of tips.

Outcome: the client trusts **cryptography + published checkpoints**, not the server process.

---

## Threats & mitigations

- **Withholding:** server omits certain blocks from checkpoints.  
  - *Mitigation:* clients compare their local receipts (e.g., ingest responses or observed block headers) against **history**; missing tips are detectable.

- **Rollback:** server tries to republish an older `latest.json`.  
  - *Mitigation:* **history** is append-only; a rollback contradicts previously published snapshots. Clients require non-decreasing tips.

- **Rewriting history:** mutate or delete old history objects.  
  - *Mitigation:* public bucket objects are immutable; bucket versioning enabled. External mirrors or signatures can further harden this (future enhancement).

- **Equivocation across regions/replicas:** different readers see different latest tips.  
  - *Mitigation:* readers check **history** continuity; any fork (two different tips with the same predecessor) is detectable.

---

## Operational notes

- **Publication transaction:** atomically write the history snapshot first, then update `latest.json`.  
- **Clock source:** use server-side publication time for `published_at`; clients treat it as advisory (chain order derives from the `prev_link_hash` links).
- **Retention:** retain **history** indefinitely; it is the audit record of monotonic growth.

---

## Design invariants (must always hold)

- Every published `latest.json` **points to** a block whose `link_hash` correctly hashes its block header.  
- The sequence formed by following `prev_link_hash` from any **latest** is linear (no branches) and reaches earlier checkpoints for the same tenant.  
- Once a history snapshot is published, its content is never altered or removed.

---

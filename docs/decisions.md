# docs/decisions.md

Default decisions for \textbf{MerkleLake}. Each item includes a one-sentence rationale so future changes are explicit and auditable.

- **Hash:** `SHA-256` with odd-level padding by duplicating the last leaf.  
  *Rationale:* SHA-256 is a widely vetted CRHF and duplicate-last padding keeps the tree complete without introducing length-dependent ambiguity in proof verification.

- **Block policy:** **max(10k events, 2s)**, whichever happens first.  
  *Rationale:* This bound amortizes seal/storage overhead while capping proof depth and end-to-end ingest freshness for near-real-time search.

- **Auth:** **JWT** for client requests; **mTLS** for node↔node communications.  
  *Rationale:* JWT scales with multi-tenant client access and short-lived tokens, while mTLS provides strong mutual authentication and on-the-wire confidentiality within the control plane.

- **Routing cadence:** recompute assignment every **1s** with a **10s** stickiness window.  
  *Rationale:* A 1s cycle reacts to load/latency shifts quickly, and stickiness suppresses flapping so batches don’t thrash across nodes.

- **Failure semantics:** \textbf{Sealing/storage is authoritative}; Elasticsearch reindexing may lag.  
  *Rationale:* Integrity must never depend on index availability—blocks are immutable truth, and the index is an eventually-consistent accelerator.

- **Checkpoint cadence:** publish the latest chain tip every **60s** to a public bucket key.  
  *Rationale:* One-minute anchoring meaningfully limits rollback windows while avoiding excessive churn and storage noise.

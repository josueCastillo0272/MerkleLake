# Architecture Overview

## Components and Responsibilities

### Ingest API

Accepts logs/events from clients and batches them for the Sealer.  
Batching allows high-volume ingestion with strong amortized performance.

### Sealer

Builds a Merkle tree from each batch and links the resulting Merkle root into the append-only chain of prior blocks.

### Object Storage

Immutable storage for raw logs and Merkle block headers.

### Search Index

Backed by Elasticsearch.  
Stores metadata such as `tenant`, `timestamp`, `block_id`, and `leaf_idx` to enable fast, queryable lookups.

### Proof Builder

Given a query result `(block_id, leaf_idx)`, reconstructs the Merkle authentication path from leaf to root.

### Routing Proxy

Front-end load-balancer that directs incoming batches to the optimal ingest node (lowest latency + load), using a min-cost-flow formulation.

### Checkpoint Publisher

Publishes the latest Merkle root hash to a public, auditable location.

---

## Request / Response Flow

Ingest → Batch → Seal (Merkle+chain) → Store (S3/MinIO) → Index (ES) → Query → Proofs → Client Verification.

---

## Trust Model

- The server cannot undetectably mutate logs; any tampering breaks Merkle proofs or diverges from the published checkpoint.

---

## Performance Goals

| Operation      | Complexity Target               |
|----------------|----------------------------------|
| Ingest         | **O(n)**                         |
| Proof Size     | **O(log n)**                     |
| Query/Search   | **O(k log n)** for *k* results   |
| Verification   | **O(log n)**                     |
| Routing        | **O(F × E log V)**               |

---

## Risk Mitigations

- Payload bloat  
- Skewed tenants (large or imbalanced request sizes)  
- Clock skew (`ts_start`, `ts_end` included per entry)  
- Mapping drift  
- Proof cache staleness  

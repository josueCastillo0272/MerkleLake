# MerkleLake

**MerkleLake** is a tamper-evident, verifiable log storage system. It ingests log events, seals them into cryptographically linked blocks using Merkle Trees, stores the raw data in immutable object storage (S3/MinIO), and indexes metadata in Elasticsearch for fast retrieval.

Every search result includes the data necessary to cryptographically verify that the log entry has not been altered since insertion and is part of a linear, append-only chain.

## Key Features

* **Tamper-Evidence:** Logs are sealed in batches. Each batch produces a Merkle Root.
* **Immutable History:** Blocks are linked via a hash chain (blockchain-style). Modifying an old block breaks the chain.
* **Verifiable Search:** Search results (from Elasticsearch) can be cross-verified against the immutable object storage using Merkle Inclusion Proofs.
* **Scalable Storage:** Raw event data is stored in object storage (MinIO/S3), while lightweight metadata is indexed in Elasticsearch.
* **Public Anchoring:** Supports publishing "checkpoints" to a public location to prevent history rewriting/split-view attacks.

## Architecture

The system consists of the following core components:

1.  **Ingest API (FastAPI):** Accepts logs, batches them, and orchestrates sealing.
2.  **Sealer:** Canonicalizes events, builds a Merkle Tree, and computes the Block Header.
3.  **Object Storage (MinIO):** Stores the immutable artifacts:
    * `merklelake-blocks`: JSON headers containing roots and chain links.
    * `merklelake-events`: Raw JSONL event payloads.
    * `merklelake-public`: Public checkpoints.
4.  **Search Index (Elasticsearch):** Indexes metadata (`tenant_id`, `timestamp`, `block_id`, `leaf_idx`) for querying.

## Prerequisites

* **Python 3.10+**
* **Docker & Docker Compose** (for running local infrastructure)

## Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/josuecastillo0272/merklelake.git
    cd merklelake
    ```


2.  **Start Infrastructure (MinIO, Elasticsearch, Redis):**
    ```bash
    docker-compose up -d
    ```

3.  **Create a Virtual Environment and Install Dependencies:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    pip install .
    ```

## Running the Server

Start the FastAPI server using Uvicorn:

```bash
uvicorn merklelake.api:app --reload --host 0.0.0.0 --port 8000
```
The API will be available at `http://localhost:8000`. You can view the interactive documentation at `http://localhost:8000/docs`.

## API Usage Examples

### 1. Ingest Logs (`POST /v1/logs`)
Submit a batch of logs to be sealed.

```bash
curl -X POST http://localhost:8000/v1/logs \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme-corp",
    "events": [
      {
        "message": "User login successful",
        "attrs": {"user_id": "123", "ip": "192.168.1.1"}
      },
      {
        "message": "Database connection established",
        "attrs": {"db": "users_prod"}
      }
    ]
  }'
  ```

**Response:**

```json
{
  "block_id": "acme-corp-...",
  "root_hash": "a1b2c3d4...",
  "ts_range": [1732000000000, 1732000002000],
  "accepted_count": 2
}
```

### 2. Search Logs (`POST /v1/search`)


Search for logs using Lucene syntax.

```bash
curl -X POST http://localhost:8000/v1/search \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "acme-corp",
    "query": "message:login"
  }'
```

**Response:**

```json
{
  "hits": [
    {
      "event_meta": { ... },
      "block_id": "acme-corp-...",
      "leaf_idx": 0,
      "ingest_ts": 1732000000000
    }
  ]
}
```

### 3. Get Cryptographic Proof (GET /v1/proof)

Request a Merkle proof for a specific log entry (identified by block_id and leaf_idx from the search result).

```bash
curl "http://localhost:8000/v1/proof?tenant_id=acme-corp&block_id=<BLOCK_ID>&leaf_idx=0"
```

```json
{
  "leaf_idx": 0,
  "path": [
    ["<sibling_hash>", "right"],
    ["<sibling_hash>", "left"]
  ],
  "root_hash": "<merkle_root>",
  "block_header": { ... }
}
```

### 4. Get Latest Checkpoint (GET /v1/checkpoint)

Retrieve the latest "tip" of the hash chain for auditing.

```bash
curl "http://localhost:8000/v1/checkpoint?tenant_id=acme-corp"
```

**Response:**

```json
{
  "block_id": "acme-corp-2025-11-09T22:59:00Z-0019",
  "link_hash": "f7b0c8d9e1a2...",
  "prev_link_hash": "2f9b4c8d1e7a...",
  "published_at": "2025-11-09T23:00:00Z"
}
```
## Configuration

Configuration is handled via environment variables.  
The system comes with sensible defaults for local development (matching `docker-compose.yml`).

| Variable                       | Default                 | Description                      |
| ----------------------------- | ----------------------- | -------------------------------- |
| `MERKLELAKE_MINIO_ENDPOINT`   | `localhost:9000`        | MinIO/S3 API Endpoint            |
| `MERKLELAKE_MINIO_ACCESS_KEY` | `minioadmin`            | MinIO Access Key                 |
| `MERKLELAKE_MINIO_SECRET_KEY` | `minioadmin`            | MinIO Secret Key                 |
| `MERKLELAKE_MINIO_SECURE`     | `false`                 | Use HTTPS for Object Storage     |
| `MERKLELAKE_ES_URL`           | `http://localhost:9200` | Elasticsearch Connection URL     |

---

## Testing

The project includes a suite of specification tests (`tests/*_spec.py`)  
that verify the cryptographic correctness and storage logic.

To run tests:

```bash
pytest
```
---

## Project Structure

src/merklelake/api.py — FastAPI routes and application entry point  
src/merklelake/ingest.py — Orchestrates sealing, storage, and indexing  
src/merklelake/seal.py — Canonicalization and Merkle tree construction  
src/merklelake/storage.py — MinIO/S3 storage adapter  
src/merklelake/es.py — Elasticsearch adapter  
src/merklelake/proofs/ — Core cryptographic logic (Merkle math, Chain headers)  
docs/ — Detailed architectural documentation  

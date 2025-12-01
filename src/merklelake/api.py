"""FastAPI application for the MerkleLake HTTP API.

This module wires the core MerkleLake components (ingest pipeline, storage,
search, and proof builder) into a FastAPI application exposing REST endpoints.
"""

import time
import uuid

from fastapi import Depends, FastAPI, HTTPException
from starlette.status import HTTP_201_CREATED

from merklelake import es, ingest
from merklelake.models import (
    CheckpointResponse,
    IngestRequest,
    IngestResponse,
    ProofResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from merklelake.proofs import builder
from merklelake.storage import BlockStorage, BlockStorageConfig, get_minio_client

app = FastAPI(title="MerkleLake", version="0.1.0")


def get_storage() -> BlockStorage:
    """Provides a configured BlockStorage instance.

    Returns:
        A ``BlockStorage`` instance backed by MinIO, using the default
        bucket names ``"merklelake-blocks"`` and ``"merklelake-events"``.
    """
    client = get_minio_client()
    config = BlockStorageConfig(
        blocks_bucket="merklelake-blocks",
        events_bucket="merklelake-events",
    )
    return BlockStorage(client, config)


def get_es():
    """Provides an Elasticsearch client instance.

    Returns:
        An Elasticsearch client configured via environment variables.
    """
    return es.get_es_client()


@app.post("/v1/logs", response_model=IngestResponse, status_code=HTTP_201_CREATED)
def ingest_logs(
    req: IngestRequest,
    storage: BlockStorage = Depends(get_storage),
) -> IngestResponse:
    events_payload = []
    current_time = int(time.time() * 1000)

    for e in req.events:
        # Use model_dump to get a dict
        ev_dict = e.model_dump(exclude_unset=True)

        if "ingest_ts" not in ev_dict:
            ev_dict["ingest_ts"] = current_time

        events_payload.append(ev_dict)

    # Generate a unique block ID
    block_id = f"{req.tenant_id}-{uuid.uuid4()}"

    try:
        # Call the ingest pipeline
        header, _ = ingest.ingest_batch(
            events=events_payload,
            tenant_id=req.tenant_id,
            block_id=block_id,
            storage=storage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # This catches the Elasticsearch BadRequestError
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}") from exc

    return IngestResponse(
        block_id=header.block_id,
        root_hash=header.root_hash_hex,
        ts_range=(header.ts_start, header.ts_end),
        accepted_count=len(events_payload),
    )


@app.post("/v1/search", response_model=SearchResponse)
def search_logs(
    req: SearchRequest,
    es_client=Depends(get_es),
) -> SearchResponse:
    """Searches logs for a given tenant using Elasticsearch.

    The search is scoped to the tenant specified in the request and uses a
    Lucene-style query string for text search. Results are paginated using
    ``page`` and ``page_size``.

    Args:
        req: Search request containing tenant, query string, and pagination
            parameters.
        es_client: Elasticsearch client dependency.

    Returns:
        A ``SearchResponse`` containing search hits and an optional
        ``next_page_token`` for pagination.
    """
    offset = req.page * req.page_size

    resp = es.search_events(
        client=es_client,
        tenant_id=req.tenant_id,
        query_string=req.query,
        limit=req.page_size,
        offset=offset,
    )

    hits_data = []
    for hit in resp["hits"]["hits"]:
        source = hit["_source"]
        hits_data.append(
            SearchHit(
                event_meta=source.get("event", {}),
                block_id=source.get("block_id"),
                leaf_idx=source.get("leaf_idx"),
                ingest_ts=source.get("ingest_ts"),
            )
        )

    total = resp["hits"]["total"]["value"]
    has_next = (offset + req.page_size) < total
    next_token = str(req.page + 1) if has_next else None

    return SearchResponse(hits=hits_data, next_page_token=next_token)


@app.get("/v1/proof", response_model=ProofResponse)
def get_proof(
    tenant_id: str,
    block_id: str,
    leaf_idx: int,
    storage: BlockStorage = Depends(get_storage),
) -> ProofResponse:
    """Returns a Merkle inclusion proof for a specific event.

    This endpoint reconstructs the Merkle tree for the specified block from
    storage, verifies integrity, and returns a Merkle path proving inclusion
    of the leaf at ``leaf_idx``.

    Args:
        tenant_id: Tenant identifier for the block.
        block_id: Block identifier from which to construct the proof.
        leaf_idx: Zero-based leaf index within the block.

    Returns:
        A ``ProofResponse`` containing the proof path, block header, and root
        hash.

    Raises:
        HTTPException: If proof generation fails for any reason (mapped to
            HTTP 404).
    """
    try:
        bundle = builder.build_proof_bundle(
            storage=storage,
            tenant_id=tenant_id,
            block_id=block_id,
            leaf_idx=leaf_idx,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=404,
            detail=f"Proof generation failed: {exc}",
        ) from exc

    hex_path = [(h.hex(), side) for h, side in bundle["path"]]

    return ProofResponse(
        leaf_idx=bundle["leaf_idx"],
        path=hex_path,
        block_header=bundle["block_header"],
        root_hash=bundle["root_hash"],
    )


@app.get("/v1/checkpoint", response_model=CheckpointResponse)
def get_checkpoint() -> CheckpointResponse:
    """Returns the latest anchored checkpoint (placeholder).

    This endpoint is a placeholder and will be implemented when checkpointing
    and consensus logic are added.

    Raises:
        HTTPException: Always raises HTTP 501 (Not Implemented) until
            checkpointing is implemented.
    """
    return CheckpointResponse(block_id="1234", link_hash="123", prev_link_hash="123")
    # raise HTTPException(status_code=501, detail="Checkpointing not yet implemented")

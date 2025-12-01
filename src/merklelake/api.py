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
from merklelake.checkpoint import publish_checkpoint

from merklelake.proofs import builder
from merklelake.storage import BlockStorage, BlockStorageConfig, get_minio_client
from dataclasses import asdict

app = FastAPI(title="MerkleLake", version="0.1.0")


def get_storage() -> BlockStorage:
    """Provides a configured BlockStorage instance."""
    client = get_minio_client()
    config = BlockStorageConfig(
        blocks_bucket="merklelake-blocks",
        events_bucket="merklelake-events",
        public_bucket="merklelake-public",
    )
    return BlockStorage(client, config)


def get_es():
    """Provides an Elasticsearch client instance."""
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
        # 1. Seal and store the block
        header, _ = ingest.ingest_batch(
            events=events_payload,
            tenant_id=req.tenant_id,
            block_id=block_id,
            storage=storage,
        )

        # 2. NEW: Publish the checkpoint immediately
        # This writes to 'merklelake-public/checkpoints/{tenant}/latest.json'
        # so that GET /v1/checkpoint can find it.
        publish_checkpoint(storage, header)

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
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
    try:
        bundle = builder.build_proof_bundle(
            storage=storage,
            tenant_id=tenant_id,
            block_id=block_id,
            leaf_idx=leaf_idx,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Proof generation failed: {exc}",
        ) from exc

    hex_path = [(h.hex(), side) for h, side in bundle["path"]]

    return ProofResponse(
        leaf_idx=bundle["leaf_idx"],
        path=hex_path,
        block_header=asdict(bundle["block_header"]),
        root_hash=bundle["root_hash"],
    )


@app.get("/v1/checkpoint", response_model=CheckpointResponse)
def get_checkpoint(
    tenant_id: str,
    storage: BlockStorage = Depends(get_storage),
) -> CheckpointResponse:
    """Returns the latest anchored checkpoint.

    Fetches the latest.json from the public bucket for the given tenant.
    """
    data = storage.get_checkpoint(tenant_id)
    if not data:
        raise HTTPException(status_code=404, detail="No checkpoint found for tenant")

    return CheckpointResponse(**data)

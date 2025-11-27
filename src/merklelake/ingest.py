"""
Ingest pipeline for MerkleLake.

This module defines the high-level operation that takes a batch of raw events,
seals them into a Merkle block, stores the block in object storage, and indexes
the events into Elasticsearch.

It is the core operation that the future FastAPI `/v1/logs` endpoint will call.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .proofs.chain import BlockHeader, ZERO_LINK
from .seal import seal_block
from .storage import BlockStorage, BlockStorageConfig, get_minio_client
from .es import index_events_from_jsonl, get_es_client


def ingest_batch(
    *,
    events: List[Dict],
    tenant_id: str,
    block_id: str,
    prev_link_hash_hex: str = ZERO_LINK,
    storage: Optional[BlockStorage] = None,
) -> Tuple[BlockHeader, str]:
    """
    Seal and persist a batch of events as a MerkleLake block.

    Inputs:
        - events: list of event dicts, each containing at least "ingest_ts".
        - tenant_id: tenant identifier for multi-tenancy scoping.
        - block_id: caller-chosen unique identifier for this block.
        - prev_link_hash_hex: link hash of the previous block in the chain
            (defaults to ZERO_LINK for genesis).
        - storage: optional BlockStorage instance; if None, ingest_batch
            will construct a default BlockStorage using get_minio_client().

    Outputs:
        - (header, root_hash_hex):
            header: BlockHeader for the sealed block.
            root_hash_hex: convenience copy of header.root_hash_hex.
    """
    # 1) Basic input validation.
    if not isinstance(events, list) or not events:
        raise ValueError("events must be a non-empty list of dicts")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("tenant_id must be a non-empty string")
    if not isinstance(block_id, str) or not block_id:
        raise ValueError("block_id must be a non-empty string")

    # Optional: check that all items are dicts (seal_block will also validate).
    if any(not isinstance(ev, dict) for ev in events):
        raise TypeError("All events must be dicts")

    # 2) Seal the batch into a Merkle block.
    header, events_jsonl, _levels = seal_block(
        events=events,
        tenant_id=tenant_id,
        block_id=block_id,
        prev_link_hash_hex=prev_link_hash_hex,
    )

    # 3) Ensure we have a BlockStorage instance (construct default if needed).
    if storage is None:
        minio_client = get_minio_client()
        # Default bucket names; must match storage layout docs.
        config = BlockStorageConfig(
            blocks_bucket="merklelake-blocks",
            events_bucket="merklelake-events",
        )
        storage = BlockStorage(client=minio_client, config=config)

    # 4) Persist header + events JSONL to object storage.
    storage.put_block(header, events_jsonl)

    # 5) Index events into Elasticsearch.
    es_client = get_es_client()
    index_events_from_jsonl(
        header=header,
        events_jsonl=events_jsonl,
        client=es_client,
    )

    # 6) Return header and root hash hex (convenience).
    return header, header.root_hash_hex

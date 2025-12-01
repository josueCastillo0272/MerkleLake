"""
Pydantic models for the MerkleLake HTTP API.

These models define the request and response schemas for the public API
endpoints. See ``docs/api-contracts.md`` for a human-readable overview.
"""

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Represents a single ingested log event.

    Attributes:
        timestamp: Optional timestamp string for the event (format is
            application-defined; typically ISO 8601).
        attrs: Arbitrary structured metadata attached to the event.
        message: Primary human-readable message for the event.
    """

    timestamp: Optional[str] = None
    attrs: Dict[str, Any] = Field(default_factory=dict)
    message: str


class BlockHeaderModel(BaseModel):
    """Wire-format representation of a sealed block header.

    This mirrors the internal ``BlockHeader`` dataclass used in the sealing
    pipeline, but is shaped for JSON API responses.

    Attributes:
        block_id: Unique identifier for the block within a tenant.
        tenant_id: Tenant identifier for the block.
        ts_start: Inclusive start of the time window covered by the block.
        ts_end: End of the time window covered by the block
            (inclusive or exclusive per system-wide convention).
        root_hash_hex: Hex-encoded Merkle root for the block's events.
        prev_link_hash_hex: Hex-encoded link hash of the previous block in
            the chain, or the genesis value for the first block.
        link_hash_hex: Hex-encoded link hash for this block.
    """

    block_id: str
    tenant_id: str
    ts_start: int
    ts_end: int
    root_hash_hex: str
    prev_link_hash_hex: str
    link_hash_hex: str


class IngestRequest(BaseModel):
    """Request payload for the ingest endpoint.

    Attributes:
        tenant_id: Tenant identifier associated with the incoming events.
        events: List of events to ingest and seal into a block.
        idempotency_key: Optional key to deduplicate repeated ingest attempts.
    """

    tenant_id: str
    events: List[Event]
    idempotency_key: Optional[str] = None


class IngestResponse(BaseModel):
    """Response payload returned after successfully sealing a block.

    Attributes:
        block_id: Identifier of the sealed block.
        root_hash: Hex-encoded Merkle root for the block.
        ts_range: Tuple ``(ts_start, ts_end)`` for the block's time window.
        accepted_count: Number of events accepted and sealed in the block.
    """

    block_id: str
    root_hash: str
    ts_range: Tuple[int, int]
    accepted_count: int


class SearchRequest(BaseModel):
    """Request payload for the event search endpoint.

    Attributes:
        tenant_id: Tenant identifier used to scope the search.
        query: Lucene-style query string (defaults to "*" for match-all).
        page_size: Maximum number of hits to return per page.
        page: Zero-based page index for pagination.
    """

    tenant_id: str
    query: str = "*"
    page_size: int = 10
    page: int = 0


class SearchHit(BaseModel):
    """Single search hit returned from the search endpoint.

    Attributes:
        event_meta: Searchable metadata and/or original event fields.
        block_id: Identifier of the block containing the event.
        leaf_idx: Leaf index of the event within the block's Merkle tree.
        ingest_ts: Ingest timestamp associated with the event.
    """

    event_meta: Dict[str, Any]
    block_id: str
    leaf_idx: int
    ingest_ts: int


class SearchResponse(BaseModel):
    """Response payload for the search endpoint.

    Attributes:
        hits: List of search hits for the current page.
        next_page_token: Optional opaque token for fetching subsequent pages.
    """

    hits: List[SearchHit]
    next_page_token: Optional[str] = None


class ProofResponse(BaseModel):
    """Response payload for the proof endpoint.

    The Merkle path is serialized as a list of ``(sibling_hash_hex, side)``
    tuples, where ``sibling_hash_hex`` is a hex string and ``side`` is
    ``"left"`` or ``"right"``.

    Attributes:
        leaf_idx: Leaf index of the event within the block's Merkle tree.
        path: Merkle path encoded as ``[(hash_hex, side), ...]``.
        block_header: Block header corresponding to the proof.
        root_hash: Hex-encoded Merkle root for the block.
    """

    leaf_idx: int
    path: List[Tuple[str, str]]
    block_header: BlockHeaderModel
    root_hash: str


class CheckpointResponse(BaseModel):
    """Response payload for the checkpoint endpoint.

    Attributes:
        block_id: Identifier of the latest anchored block.
        link_hash: Hex-encoded link hash for the checkpoint block.
        prev_link_hash: Hex-encoded link hash of the previous block.
        published_at: Optional timestamp indicating when the checkpoint was
            published.
    """

    block_id: str
    link_hash: str
    prev_link_hash: str
    published_at: Optional[str] = None

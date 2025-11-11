from __future__ import annotations

import json
from typing import Dict, List, Tuple

from .proofs.merkle import build_levels, root_of, b2hex  # to be implemented by you
from .proofs.chain import (
    BlockHeader,
    make_header,
    ZERO_LINK,
)  # to be implemented by you


def _canon_event_bytes(ev: Dict) -> bytes:
    """
    Canonical JSON encoding for events (must match JSONL line bytes exactly).

    Contract:
    - Use json.dumps with:
        sort_keys=True
        ensure_ascii=False
        separators=(',', ':')   # no spaces after commas/colons
    - Encode with UTF-8 (no BOM).
    - NEVER pretty-print (whitespace changes hashes).
      - Event *must* be serializable and contain only JSON-safe types.

    Returns:
    bytes of the canonical JSON string.

    Raises:
    TypeError / ValueError if ev is not serializable or required keys missing (see _order_events).

    Acceptance checks:
    - Re-encoding the same dict yields identical bytes (determinism).
    - Hashing these bytes produces leaf hashes equal to those used to build the tree.
    """
    raise NotImplementedError("Return canonical UTF-8 bytes for the event JSON")


def _order_events(events: List[Dict]) -> List[Dict]:
    """
    Deterministic ordering: primary by 'ingest_ts' ascending (int),
    secondary by original input order (stable sort).

    Requirements:
    - Each event MUST include: 'ingest_ts' (int). Validate type.
    - Do NOT mutate observable fields (safe to attach a temporary index tag
        but remove it before returning).

    Returns:
    New list with events ordered deterministically.

    Raises:
    KeyError if 'ingest_ts' missing.
    TypeError if 'ingest_ts' is not int.

    Acceptance checks:
    - Equal timestamps preserve initial relative order (stability).
    - Sealing the same input twice yields identical order.
    """
    raise NotImplementedError("Stable sort by (ingest_ts, original_position)")


def _to_jsonl(ordered_events: List[Dict]) -> str:
    """
    Render events to JSON Lines (JSONL) text:
    - One canonicalized JSON object per line.
    - Use the same canonicalization as _canon_event_bytes.
    - No trailing newline at end of file.

    Returns:
    JSONL string. Line i (0-based) corresponds to leaf_idx i.

    Acceptance checks:
    - Splitting by '\n' produces len == len(ordered_events).
    - Encoding line i back to bytes reproduces the exact bytes hashed for leaf i.
    """
    raise NotImplementedError(
        "Join canonical JSON strings with '\\n' (no trailing newline)"
    )


def seal_block(
    *,
    events: List[Dict],
    tenant_id: str,
    block_id: str,
    prev_link_hash_hex: str = ZERO_LINK,
) -> Tuple[BlockHeader, str, List[List[bytes]]]:
    """
    Seal a batch of events into an in-memory block (Week 1; no storage yet).

    Pipeline (each step must be deterministic):
    1) Order events with _order_events (by ingest_ts, then stable tie-break).
    2) Produce JSONL text with _to_jsonl (canonical encoding).
    3) Build Merkle levels from the EXACT bytes used in JSONL lines.
        (leaf_idx == line_number invariant)
    4) Compute root = root_of(levels).
    5) Derive BlockHeader via make_header with:
        tenant_id, block_id, ts_start=min(ingest_ts), ts_end=max(ingest_ts),
        root_hash_hex=b2hex(root), prev_link_hash_hex as provided.

    Returns:
    (header: BlockHeader, events_jsonl_text: str, merkle_levels: List[List[bytes]])

    Raises:
    ValueError if events is empty.
    KeyError/TypeError bubbles from _order_events for missing/invalid ingest_ts.

    Acceptance checks:
    - Determinism: sealing the same input twice yields identical JSONL and identical root.
    - Mapping: for each line i, verify inclusion of line_bytes with proof_for(levels, i).
    - Tamper: change one char in line j -> verification for leaf_idx=j must fail.
    """
    raise NotImplementedError(
        "Implement in-memory sealing pipeline and return (header, jsonl, levels)"
    )

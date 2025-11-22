from __future__ import annotations

import json
from typing import Dict, List, Tuple

from .proofs.merkle import build_levels, root_of, b2hex
from .proofs.chain import (
    BlockHeader,
    make_header,
    ZERO_LINK,
)


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
    # json.dumps will raise TypeError/ValueError on non-serializable input.
    s = json.dumps(
        ev,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return s.encode("utf-8")


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
    indexed: List[Tuple[int, int, Dict]] = []

    for pos, ev in enumerate(events):
        if "ingest_ts" not in ev:
            raise KeyError("Event missing required 'ingest_ts' field")
        ts = ev["ingest_ts"]
        if not isinstance(ts, int):
            raise TypeError("'ingest_ts' must be an int")
        indexed.append((ts, pos, ev))

    # Sort by (ingest_ts, original_position) to guarantee determinism.
    indexed.sort(key=lambda t: (t[0], t[1]))

    # Return only the original event dicts, in new order.
    return [ev for _, _, ev in indexed]


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
    lines: List[str] = [_canon_event_bytes(ev).decode("utf-8") for ev in ordered_events]
    # join() on empty list returns "", so no trailing newline either way.
    return "\n".join(lines)


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
    if not events:
        raise ValueError("Cannot seal an empty event batch")

    # 1) Deterministic ordering by ingest_ts (then stable tie-break).
    ordered_events = _order_events(events)

    # 2) Canonical JSONL text.
    events_jsonl_text = _to_jsonl(ordered_events)

    # 3) Build Merkle levels from EXACT canonical bytes.
    leaf_payloads: List[bytes] = [_canon_event_bytes(ev) for ev in ordered_events]
    merkle_levels = build_levels(leaf_payloads)

    # 4) Compute root hash.
    root = root_of(merkle_levels)

    # 5) Build BlockHeader with timestamp range and root.
    ingest_ts_values = [ev["ingest_ts"] for ev in ordered_events]
    ts_start = min(ingest_ts_values)
    ts_end = max(ingest_ts_values)

    header = make_header(
        tenant_id=tenant_id,
        block_id=block_id,
        ts_start=ts_start,
        ts_end=ts_end,
        root_hash_hex=b2hex(root),
        prev_link_hash_hex=prev_link_hash_hex,
    )

    return header, events_jsonl_text, merkle_levels

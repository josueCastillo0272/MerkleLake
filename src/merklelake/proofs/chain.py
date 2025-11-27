from __future__ import annotations

from dataclasses import dataclass
import hashlib

ZERO_LINK: str = "0" * 64  # 32-byte link hash encoded as hex (genesis prev_link)


@dataclass(frozen=True)
class BlockHeader:
    """
    Minimal block header that binds a Merkle root to a hash-chain.

    Fields:
    block_id : str  - unique identifier for the block (format T.B.D. later)
    tenant_id: str  - multi-tenant scoping
    ts_start: int  - start of time window (pick one unit and keep it: seconds or ms)
    ts_end: int  - end of time window (inclusive or exclusive: document and use consistently)
    root_hash_hex: str  - lowercase hex of the Merkle root
    prev_link_hash_hex: str  - lowercase hex link hash from previous block (ZERO_LINK for first)
    link_hash_hex: str  - lowercase hex link for this block (derived; see compute_link_hash_hex)

    Invariants (must hold after construction):
    - len(prev_link_hash_hex) == 64 and len(link_hash_hex) == 64
    - ts_start <= ts_end
    - root_hash_hex is 64-len hex
    - All hex strings are lowercase
    """

    block_id: str
    tenant_id: str
    ts_start: int
    ts_end: int
    root_hash_hex: str
    prev_link_hash_hex: str
    link_hash_hex: str


def _canonical_header_string(
    block_id: str,
    tenant_id: str,
    ts_start: int,
    ts_end: int,
    root_hash_hex: str,
    prev_link_hash_hex: str,
) -> str:
    """
    Deterministic concatenation recipe for computing link_hash_hex.

    Contract:
    - EXACT order with '|' delimiter:
        f"{block_id}|{tenant_id}|{ts_start}|{ts_end}|{root_hash_hex}|{prev_link_hash_hex}"
    """
    return (
        f"{block_id}|{tenant_id}|{ts_start}|{ts_end}|"
        f"{root_hash_hex}|{prev_link_hash_hex}"
    )


def compute_link_hash_hex(
    block_id: str,
    tenant_id: str,
    ts_start: int,
    ts_end: int,
    root_hash_hex: str,
    prev_link_hash_hex: str,
) -> str:
    """
    Compute lowercase-hex SHA-256 over the canonical header string.

    Returns:
    64-char lowercase hex link for this header.
    """
    # Basic validation: 64-char hex strings and non-decreasing timestamps.
    if len(root_hash_hex) != 64:
        raise ValueError("root_hash_hex must be a 64-character hex string")
    if len(prev_link_hash_hex) != 64:
        raise ValueError("prev_link_hash_hex must be a 64-character hex string")

    # Validate that they are actually hex.
    try:
        int(root_hash_hex, 16)
        int(prev_link_hash_hex, 16)
    except ValueError as exc:
        raise ValueError(
            "root_hash_hex and prev_link_hash_hex must be valid hex"
        ) from exc

    if ts_start > ts_end:
        raise ValueError("ts_start must be <= ts_end")

    s = _canonical_header_string(
        block_id=block_id,
        tenant_id=tenant_id,
        ts_start=ts_start,
        ts_end=ts_end,
        root_hash_hex=root_hash_hex,
        prev_link_hash_hex=prev_link_hash_hex,
    )
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def link_hash(header: BlockHeader) -> str:
    """
    Recompute the link hash for an existing BlockHeader.

    Returns:
        64-char lowercase hex string, equal to header.link_hash_hex
        if the header fields have not been modified.
    """
    return compute_link_hash_hex(
        block_id=header.block_id,
        tenant_id=header.tenant_id,
        ts_start=header.ts_start,
        ts_end=header.ts_end,
        root_hash_hex=header.root_hash_hex,
        prev_link_hash_hex=header.prev_link_hash_hex,
    )


def make_header(
    *,
    block_id: str,
    tenant_id: str,
    ts_start: int,
    ts_end: int,
    root_hash_hex: str,
    prev_link_hash_hex: str = ZERO_LINK,
) -> BlockHeader:
    """
    Assemble a BlockHeader and compute its link_hash_hex.

    Returns:
    BlockHeader

    Raises:
    ValueError on malformed inputs (bad hex length, bad timestamps).
    """
    # 1) Normalize input hex strings to lowercase.
    root_hash_hex = root_hash_hex.lower()
    prev_link_hash_hex = prev_link_hash_hex.lower()

    # 2) Validate lengths (64) and ts_start <= ts_end.
    if len(root_hash_hex) != 64:
        raise ValueError("root_hash_hex must be a 64-character hex string")
    if len(prev_link_hash_hex) != 64:
        raise ValueError("prev_link_hash_hex must be a 64-character hex string")
    if ts_start > ts_end:
        raise ValueError("ts_start must be <= ts_end")

    # 3) Derive link_hash_hex.
    link_hash_hex = compute_link_hash_hex(
        block_id=block_id,
        tenant_id=tenant_id,
        ts_start=ts_start,
        ts_end=ts_end,
        root_hash_hex=root_hash_hex,
        prev_link_hash_hex=prev_link_hash_hex,
    )

    # 4) Return BlockHeader dataclass with all fields set.
    return BlockHeader(
        block_id=block_id,
        tenant_id=tenant_id,
        ts_start=ts_start,
        ts_end=ts_end,
        root_hash_hex=root_hash_hex,
        prev_link_hash_hex=prev_link_hash_hex,
        link_hash_hex=link_hash_hex,
    )

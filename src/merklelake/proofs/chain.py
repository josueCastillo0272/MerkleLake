from __future__ import annotations

from dataclasses import dataclass

ZERO_LINK: str = "0" * 64  # 32-byte link hash encoded as hex (genesis prev_link)


@dataclass(frozen=True)
class BlockHeader:
    """
    Minimal block header that binds a Merkle root to a hash-chain.

    Fields:
    block_id           : str  - unique identifier for the block (format T.B.D. later)
    tenant_id          : str  - multi-tenant scoping
    ts_start           : int  - start of time window (pick one unit and keep it: seconds or ms)
    ts_end             : int  - end of time window (inclusive or exclusive: document and use consistently)
    root_hash_hex      : str  - lowercase hex of the Merkle root
    prev_link_hash_hex : str  - lowercase hex link hash from previous block (ZERO_LINK for first)
    link_hash_hex      : str  - lowercase hex link for this block (derived; see compute_link_hash_hex)

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
    - root_hash_hex and prev_link_hash_hex MUST be lowercase hex (validate upstream).
    - No surrounding whitespace, no trailing delimiter.
    - Timestamps must be plain decimal strings (no zero padding).

    Why:
    - Any change to field values or order must change the link hash.
      - The recipe is part of the *protocol*; never silently change it.

    Returns:
    The canonical string to be hashed with SHA-256.

    NOTE: Implement here as a pure function; do not hash yet.
    """
    raise NotImplementedError("Return the exact pipe-delimited canonical string")


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

    Implementation guidance:
    - Use hashlib.sha256(s.encode('utf-8')).hexdigest()
    - Must produce 64-character lowercase hex.

    Input validation (recommended):
    - root_hash_hex and prev_link_hash_hex are 64-hex strings.
    - ts_start <= ts_end.

    Returns:
    64-char lowercase hex link for this header.
    """
    raise NotImplementedError("Hash the canonical string and return hexdigest()")


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

    Steps (exactly this order):
    1) Normalize input hex strings to lowercase.
    2) Validate lengths (64) and ts_start <= ts_end.
    3) Derive link_hash_hex = compute_link_hash_hex(...)
    4) Return BlockHeader dataclass with all fields set.

    Returns:
    BlockHeader

    Raises:
    ValueError on malformed inputs (bad hex length, bad timestamps).
    """
    raise NotImplementedError(
        "Validate inputs, compute link hash, and return BlockHeader"
    )

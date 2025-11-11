from __future__ import annotations

from typing import List, Tuple, Literal

import hashlib
import math

Side = Literal["left", "right"]
ProofStep = Tuple[
    bytes, Side
]  # (sibling_hash_bytes, side_of_sibling_relative_to_current)


def h(b: bytes) -> bytes:
    """
    SHA-256 over raw bytes.

    Returns:
        32-byte digest.

    Raises:
        TypeError if input is not bytes (caller is expected to pass bytes).
    """
    if type(b) != bytes:
        raise TypeError("Caller is expected to pass bytes.")
    return hashlib.sha256(b).digest()


def build_levels(leaves: List[bytes]) -> List[List[bytes]]:
    """
    Build all Merkle levels from ordered *leaf payload bytes*.

    Definitions:
    - Level 0 contains H(leaf_i) for each leaf payload.
    - Each higher level hashes adjacent pairs: H(left || right).
    - If a level has an odd count, duplicate the *last* node on that level
    before pairing (padding rule).

    Determinism rules:
    - Input order defines leaf indices; never reorder within this function.
    - Padding is applied *per level* (not once globally).
    - Hash concatenation order is *left then right*.

    Complexity target:
    - O(n) hashes at leaves + O(n) internal hashes; memory is O(n).

    Args:
        leaves: ordered list of raw payload bytes. len(leaves) >= 1.

    Returns:
        levels: list where levels[0] is list of leaf hashes (bytes),
                levels[-1] has length 1 (the root).

    Raises:
        ValueError: if leaves is empty.
        TypeError : if any element is not bytes.

    Acceptance checks (write tests accordingly):
    - Single leaf: root == H(leaf).
    - Three leaves: padding duplicates the 3rd hash at level 0.
    - Large n (e.g., 10_000): build finishes quickly; root exists.
    """
    if not leaves:
        raise ValueError("Leaves are empty.")
    if any(not isinstance(b, bytes) for b in leaves):
        raise TypeError("Require input as bytes.")

    # Level 0: hash the raw leaf payloads
    level = [h(b) for b in leaves]
    levels: List[List[bytes]] = [level[:]]

    # Keep building until we have a single root
    while len(level) > 1:
        work = level[:]
        if len(work) % 2 == 1:
            work.append(work[-1])

        next_level: List[bytes] = []
        for i in range(0, len(work), 2):
            left, right = work[i], work[i + 1]
            next_level.append(h(left + right))

        level = next_level
        levels.append(level[:])

    return levels


def root_of(levels: List[List[bytes]]) -> bytes:
    """
    Extract the Merkle root from levels built by `build_levels`.

    Args:
        levels: non-empty list of non-empty lists of bytes.

    Returns:
        root hash as bytes (levels[-1][0]).

    Raises:
        ValueError if levels are malformed (empty or last level empty).
    """
    if not levels:
        raise ValueError("Levels empty.\n")
    elif not levels[-1][0]:
        raise ValueError("Last level empty.\n")
    return levels[-1][0]


def proof_for(levels: List[List[bytes]], leaf_index: int) -> List[ProofStep]:
    """
    Construct an inclusion proof for a leaf index.

    Proof format:
    A list of steps from leaf level upward.
    Each step is (sibling_hash_bytes, side) where:
        - side == "left"  => sibling was LEFT of current node
        - side == "right" => sibling was RIGHT of current node

    Algorithm sketch:
    idx = leaf_index
    for each level except the top:
        if idx is even: current is LEFT child
        sibling index = idx + 1 (or idx itself if padded)
        append (sibling_hash, "right")
        else: current is RIGHT child
        sibling index = idx - 1
        append (sibling_hash, "left")
        idx //= 2

    Args:
        levels: output of build_levels
        leaf_index: 0 <= leaf_index < number_of_leaves

    Returns:
        Ordered proof steps from bottom to top (length ≈ ceil(log2(n))).

    Raises:
        ValueError: empty/malformed levels.
        IndexError: leaf_index out of range.

    Acceptance checks:
    - Proof length equals number of level transitions (≈ ceil(log2(n))).
    - For three leaves, middle leaf proof has two steps with correct sides.
    """
    ...


def verify_inclusion(
    leaf_payload: bytes, proof: List[ProofStep], claimed_root: bytes
) -> bool:
    """
    Verify that `leaf_payload` is included in a tree with `claimed_root`
    using the provided `proof`.

    Verification rule:
    cur = H(leaf_payload)
    for (sib, side) in proof:
        if side == "right": cur = H(cur || sib)
        if side == "left" : cur = H(sib || cur)
    return cur == claimed_root

    Return semantics:
    - Return True on exact equality.
    - Return False (do NOT raise) if:
          * side label is invalid,
          * proof length/shape is inconsistent,
          * concatenations don't yield the claimed root.

    Args:
        leaf_payload: raw bytes of the original leaf (identical to hashed bytes).
        proof: list of (sibling_hash_bytes, side) steps.
        claimed_root: expected root hash in raw bytes.

    Returns:
        bool: True if verified, else False.

    Acceptance checks:
    - Happy path True for proofs generated by `proof_for`.
    - Tamper 1 byte in leaf_payload => False.
    - Tamper 1 byte in any sibling => False.
    - Flip one side label => False.
    """
    raise NotImplementedError(
        "Fold proof with side-aware concatenation and compare to root"
    )


def b2hex(b: bytes) -> str:
    """
    Utility: bytes -> lowercase hex string.

    Use only for human-facing output/logging; keep internal values as bytes.
    """
    return b.hex()


def hex2b(s: str) -> bytes:
    """
    Utility: lowercase/uppercase hex string -> bytes.
    """
    return bytes.fromhex(s)

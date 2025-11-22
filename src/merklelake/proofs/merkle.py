from __future__ import annotations

from typing import List, Tuple, Literal

import hashlib

Side = Literal["left", "right"]
ProofStep = Tuple[
    bytes, Side
]  # (sibling_hash_bytes, side_of_sibling_relative_to_current)


def h(b: bytes) -> bytes:
    """Return SHA-256(b) as 32-byte digest, requiring b to be bytes."""
    if type(b) != bytes:
        raise TypeError("Caller is expected to pass bytes.")
    return hashlib.sha256(b).digest()


def build_levels(leaves: List[bytes]) -> List[List[bytes]]:
    """
    Build all Merkle tree levels from ordered leaf payload bytes.

    Level 0 = H(leaf_i). Each higher level hashes pairs H(left || right).
    If a level has an odd number of nodes, the last node is duplicated
    before pairing. The last level has length 1 (the root).
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
    Return the Merkle root (the single hash in the last level).

    Expects non-empty levels as produced by build_levels().
    """
    if not levels:
        raise ValueError("Levels must be a non-empty list.")
    last_level = levels[-1]
    if not last_level:
        raise ValueError("Last level must contain at least one hash.")
    return last_level[0]


def proof_for(levels: List[List[bytes]], leaf_index: int) -> List[ProofStep]:
    """
    Build an inclusion proof for a leaf at index `leaf_index`.

    Returns a bottom-up list of (sibling_hash, side) steps where `side`
    is "left" or "right" relative to the current node. Padding behavior
    matches build_levels: if a level is odd-length, the last node is
    paired with itself.
    """
    if not levels or not levels[0]:
        raise ValueError("Levels must be the non-empty output of build_levels().")

    num_leaves = len(levels[0])
    if leaf_index < 0 or leaf_index >= num_leaves:
        raise IndexError("leaf_index out of range for level 0.")

    idx = leaf_index
    proof: List[ProofStep] = []

    # Walk from level 0 (leaves) up to, but excluding, the root level.
    for level_hashes in levels[:-1]:
        level_len = len(level_hashes)

        if level_len == 0:
            raise ValueError("Encountered empty level while building proof.")

        if idx % 2 == 0:
            # Current node is the left child.
            if idx + 1 < level_len:
                sib_idx = idx + 1
            else:
                sib_idx = idx  # padded self
            side: Side = "right"
        else:
            # Current node is the right child; sibling is to the left.
            sib_idx = idx - 1
            side = "left"

        sibling_hash = level_hashes[sib_idx]
        proof.append((sibling_hash, side))

        # Move to the index of the parent on the next level.
        idx //= 2

    return proof


def verify_inclusion(
    leaf_payload: bytes, proof: List[ProofStep], claimed_root: bytes
) -> bool:
    """
    Verify that `leaf_payload` is in a tree with root `claimed_root`
    using an inclusion `proof` from proof_for().

    Recomputes hashes from the leaf upward; returns True if the final
    hash equals claimed_root, False on mismatch or malformed input.
    """
    # Basic type checks. If these fail, we simply decline verification.
    if not isinstance(leaf_payload, bytes) or not isinstance(claimed_root, bytes):
        return False

    try:
        cur = h(leaf_payload)
    except TypeError:
        return False

    for sibling_hash, side in proof:
        if not isinstance(sibling_hash, bytes):
            return False
        if side == "right":
            cur = h(cur + sibling_hash)
        elif side == "left":
            cur = h(sibling_hash + cur)
        else:
            # Invalid side label.
            return False

    return cur == claimed_root


def b2hex(b: bytes) -> str:
    """Convert bytes to a lowercase hex string (for logging / display)."""
    return b.hex()


def hex2b(s: str) -> bytes:
    """Convert a hex string (any case) to bytes."""
    return bytes.fromhex(s)

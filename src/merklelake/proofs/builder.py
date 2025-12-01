"""
Proof builder for MerkleLake.

This module reconstructs Merkle trees from stored events and generates
inclusion proofs for specific leaves.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from merklelake.storage import BlockStorage
from merklelake.proofs import merkle
from merklelake.proofs.chain import BlockHeader


def build_proof_bundle(
    storage: BlockStorage,
    tenant_id: str,
    block_id: str,
    leaf_idx: int,
) -> Dict[str, Any]:
    """Builds an inclusion proof bundle for a specific event.

    This function fetches the stored block header and JSONL events, reconstructs
    the Merkle tree exactly as it was sealed, verifies that the recomputed root
    matches the stored root hash, and then produces a Merkle path for the
    specified leaf index.

    The returned bundle has the following structure:

    .. code-block:: python

        {
            "leaf_idx": int,
            "path": List[Tuple[bytes, str]],  # (sibling_hash, "left" | "right")
            "block_header": BlockHeader,
            "root_hash": str,  # hex-encoded Merkle root
        }

    Args:
        storage: Storage backend used to retrieve block headers and events.
        tenant_id: Tenant identifier for the block.
        block_id: Block identifier within the tenant.
        leaf_idx: Zero-based index of the event within the block.

    Returns:
        A dictionary representing the proof bundle for the requested leaf.

    Raises:
        ValueError: If the block has no events, if ``leaf_idx`` is out of
            bounds, or if the recomputed root hash does not match the stored
            header's ``root_hash_hex`` (integrity failure).
        KeyError: Propagated from storage if required objects are missing.
        AnyException: Any other exception raised by the underlying storage
            implementation.
    """
    header = storage.get_block_header(tenant_id, block_id)
    jsonl_text = storage.get_events_jsonl(tenant_id, block_id)

    lines = jsonl_text.split("\n")

    # Handle explicit empty-block case.
    if len(lines) == 1 and not lines[0]:
        leaf_payloads: List[bytes] = []
    else:
        leaf_payloads = [line.encode("utf-8") for line in lines]

    if not leaf_payloads:
        raise ValueError(f"Block {block_id} has no events; cannot generate proof.")

    levels = merkle.build_levels(leaf_payloads)
    computed_root = merkle.root_of(levels)

    computed_root_hex = merkle.b2hex(computed_root)
    if computed_root_hex != header.root_hash_hex:
        raise ValueError(
            f"Integrity Error: Recomputed root {computed_root_hex} "
            f"does not match header root {header.root_hash_hex}"
        )

    path: List[Tuple[bytes, str]] = merkle.proof_for(levels, leaf_idx)

    return {
        "leaf_idx": leaf_idx,
        "path": path,
        "block_header": header,
        "root_hash": computed_root_hex,
    }

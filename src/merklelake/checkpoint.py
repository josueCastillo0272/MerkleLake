"""
Checkpointing logic for MerkleLake.

This module handles the construction and publication of chain checkpoints.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict

from merklelake.proofs.chain import BlockHeader
from merklelake.storage import BlockStorage


def create_checkpoint_data(header: BlockHeader) -> Dict[str, Any]:
    """Constructs the checkpoint payload from a BlockHeader.

    Fields:
        block_id: identifier of the newest sealed block
        link_hash: hash of the block header (chain tip)
        prev_link_hash: previous tip's link_hash
        published_at: ISO8601 timestamp of publication
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "block_id": header.block_id,
        "link_hash": header.link_hash_hex,
        "prev_link_hash": header.prev_link_hash_hex,
        "published_at": now_iso,
    }


def publish_checkpoint(storage: BlockStorage, header: BlockHeader) -> None:
    """Publishes a new checkpoint for the given block header.

    Writes to:
    1. merklelake-public/checkpoints/{tenant}/history/{yyyy}/{mm}/{dd}/{ts}.json
    2. merklelake-public/checkpoints/{tenant}/latest.json

    Args:
        storage: The block storage backend.
        header: The BlockHeader representing the new chain tip.
    """
    tenant_id = header.tenant_id
    data = create_checkpoint_data(header)

    # Construct history path: checkpoints/{tenant}/history/{yyyy}/{mm}/{dd}/{timestamp}.json
    dt = datetime.now(timezone.utc)
    ts_str = str(int(dt.timestamp() * 1000))  # ms precision for uniqueness
    history_key = (
        f"checkpoints/{tenant_id}/history/"
        f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}/{ts_str}.json"
    )

    storage.put_checkpoint(tenant_id, data, history_key)

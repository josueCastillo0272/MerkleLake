"""
Elasticsearch helpers for MerkleLake.

This module provides helpers to construct an Elasticsearch client, ensure the
events index exists with the expected mapping, and index sealed block events
from JSON Lines text.

It does not implement Merkle proofs. It only stores searchable metadata about
events, including ``tenant_id``, ``block_id``, ``leaf_idx``, ``root_hash_hex``,
and ``ingest_ts``.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from elasticsearch import Elasticsearch

from .proofs.chain import BlockHeader


def get_es_client() -> "Elasticsearch":
    """Creates an Elasticsearch client configured from environment variables.

    The following environment variable is consulted:

    * MERKLELAKE_ES_URL: Elasticsearch URL (default "http://localhost:9200").

    This function only constructs the client; it does not perform any health
    checks or network calls.

    Returns:
        An ``Elasticsearch`` client instance.

    Raises:
        ValueError: If the URL is empty or only whitespace.
        ImportError: If the ``elasticsearch`` package is not installed.
    """
    from elasticsearch import Elasticsearch  # type: ignore[import-not-found]

    url = os.getenv("MERKLELAKE_ES_URL", "http://localhost:9200").strip()
    if not url:
        raise ValueError("MERKLELAKE_ES_URL must not be empty")

    return Elasticsearch(hosts=[url])


def ensure_events_index(
    client: "Elasticsearch",
    index_name: str = "merklelake-events",
) -> None:
    """Ensures the events index exists with the required mapping.

    The initial mapping uses the following field types:

    * tenant_id: keyword
    * block_id: keyword
    * leaf_idx: integer
    * root_hash_hex: keyword
    * ingest_ts: long
    * event: object (enabled)

    If the index already exists, this function is a no-op.

    Args:
        client: Elasticsearch client instance.
        index_name: Name of the events index.

    Raises:
        Any exception raised by ``client.indices.exists`` or
        ``client.indices.create``.
    """
    if client.indices.exists(index=index_name):
        return

    mapping = {
        "mappings": {
            "properties": {
                "tenant_id": {"type": "keyword"},
                "block_id": {"type": "keyword"},
                "leaf_idx": {"type": "integer"},
                "root_hash_hex": {"type": "keyword"},
                "ingest_ts": {"type": "long"},
                "event": {"type": "object", "enabled": True},
            }
        }
    }

    client.indices.create(index=index_name, body=mapping)


from elasticsearch.helpers import bulk


def index_events_from_jsonl(
    header: BlockHeader,
    events_jsonl: str,
    client: "Elasticsearch",
    index_name: str = "merklelake-events",
) -> None:
    """Indexes each event from a sealed block into Elasticsearch.

    Each non-empty line in ``events_jsonl`` must be a valid JSON object with an
    integer ``ingest_ts`` field. For line index ``i``, the document schema is:

        {
            "tenant_id": header.tenant_id,
            "block_id": header.block_id,
            "leaf_idx": i,
            "root_hash_hex": header.root_hash_hex,
            "ingest_ts": event["ingest_ts"],
            "event": event,
        }
    """
    if not isinstance(events_jsonl, str):
        raise ValueError("events_jsonl must be a string")

    ensure_events_index(client, index_name=index_name)

    lines = events_jsonl.splitlines()
    actions = []

    for leaf_idx, line in enumerate(lines):
        if not line.strip():
            continue

        event = json.loads(line)

        if "ingest_ts" not in event:
            raise ValueError("Event missing required 'ingest_ts' field")
        ingest_ts = event["ingest_ts"]
        if not isinstance(ingest_ts, int):
            raise ValueError("'ingest_ts' must be an int")

        doc = {
            "tenant_id": header.tenant_id,
            "block_id": header.block_id,
            "leaf_idx": leaf_idx,
            "root_hash_hex": header.root_hash_hex,
            "ingest_ts": ingest_ts,
            "event": event,
        }

        actions.append(
            {
                "_index": index_name,
                "_source": doc,
            }
        )

    if not actions:
        return

    # High-level helper that builds the bulk request correctly
    bulk(client, actions)


def search_events(
    client: "Elasticsearch",
    tenant_id: str,
    query_string: str = "*",
    index_name: str = "merklelake-events",
    limit: int = 10,
    offset: int = 0,
) -> Dict[str, Any]:
    """Searches for events belonging to a tenant using a Lucene query string.

    This helper wraps a filtered Elasticsearch search. Results are restricted to
    the given ``tenant_id`` using a term filter, combined with a
    ``query_string`` query for text search. Results are sorted by
    ``ingest_ts`` in descending order.

    Args:
        client: Elasticsearch client instance.
        tenant_id: Tenant identifier used as a filter.
        query_string: Lucene query string (for example, "message:error" or "*").
            If blank or whitespace, it is treated as "*".
        index_name: Index to search against.
        limit: Maximum number of hits to return.
        offset: Number of hits to skip (for pagination).

    Returns:
        The raw Elasticsearch response dictionary, typically containing keys
        such as ``"took"`` and ``"hits"``.
    """
    q = query_string.strip()
    if not q:
        q = "*"

    body = {
        "query": {
            "bool": {
                "filter": [{"term": {"tenant_id": tenant_id}}],
                "must": [{"query_string": {"query": q}}],
            }
        },
        "from": offset,
        "size": limit,
        "sort": [{"ingest_ts": {"order": "desc"}}],
    }

    return client.search(index=index_name, body=body)

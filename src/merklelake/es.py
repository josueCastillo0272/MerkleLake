"""
Elasticsearch helpers for MerkleLake.
"""

from __future__ import annotations

print("--- LOADED ROBUST ES.PY ---")

import json
import os
from typing import Any, Dict, List, TYPE_CHECKING

# Import BadRequestError to catch the specific 400 error
from elasticsearch import Elasticsearch, BadRequestError
from elasticsearch.helpers import bulk

if TYPE_CHECKING:
    from .proofs.chain import BlockHeader


def get_es_client() -> "Elasticsearch":
    """Creates an Elasticsearch client configured from environment variables."""
    url = os.getenv("MERKLELAKE_ES_URL", "http://localhost:9200").strip()
    if not url:
        raise ValueError("MERKLELAKE_ES_URL must not be empty")

    return Elasticsearch(hosts=[url])


def ensure_events_index(
    client: "Elasticsearch",
    index_name: str = "merklelake-events",
) -> None:
    """Ensures the events index exists with the required mapping."""

    # Mapping definition
    mapping = {
        "properties": {
            "tenant_id": {"type": "keyword"},
            "block_id": {"type": "keyword"},
            "leaf_idx": {"type": "integer"},
            "root_hash_hex": {"type": "keyword"},
            "ingest_ts": {"type": "long"},
            "event": {"type": "object", "enabled": True},
        }
    }

    try:
        # ATTEMPT TO CREATE DIRECTLY (Bypassing .exists() check)
        # If it works -> Great, index created.
        # If it exists -> Raises BadRequestError, which we catch below.
        client.indices.create(index=index_name, mappings=mapping)
        print(f"Index '{index_name}' created successfully.")

    except BadRequestError as e:
        # Check if the error is "resource_already_exists_exception"
        if "resource_already_exists_exception" in str(e):
            # This is fine, it means the index is already there.
            pass
        else:
            # If it's a different 400 error, we re-raise it so you can see it.
            print(f"Error creating index: {e}")
            raise


def index_events_from_jsonl(
    header: "BlockHeader",
    events_jsonl: str,
    client: "Elasticsearch",
    index_name: str = "merklelake-events",
) -> None:
    """Indexes each event from a sealed block into Elasticsearch."""
    if not isinstance(events_jsonl, str):
        raise ValueError("events_jsonl must be a string")

    # Ensure index exists (using the new robust method)
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

    bulk(client, actions)


def search_events(
    client: "Elasticsearch",
    tenant_id: str,
    query_string: str = "*",
    index_name: str = "merklelake-events",
    limit: int = 10,
    offset: int = 0,
) -> Dict[str, Any]:
    """Searches for events belonging to a tenant."""
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

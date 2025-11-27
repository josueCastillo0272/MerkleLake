"""
Elasticsearch helpers for MerkleLake.

This module is responsible for:

    - Constructing an Elasticsearch client from configuration.
    - Ensuring the events index exists with the correct mappings.
    - Indexing sealed block events from JSONL into the events index.

It does NOT know about Merkle proofs; it simply stores searchable metadata
about events, including (tenant_id, block_id, leaf_idx, root_hash_hex, ingest_ts).
"""

from __future__ import annotations

import json
import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from elasticsearch import Elasticsearch

from .proofs.chain import BlockHeader


def get_es_client() -> "Elasticsearch":
    """
    Construct and return an Elasticsearch client.

    Algorithm:
        1. Read MERKLELAKE_ES_URL from environment (default "http://localhost:9200").
        2. Instantiate an Elasticsearch client pointing at that URL.
        3. Do not perform network calls here; health checks are left to callers.

    Testing strategy:
        - Unit tests can monkeypatch MERKLELAKE_ES_URL and
            stub out the Elasticsearch constructor via a fake 'elasticsearch'
            module, then assert the client was constructed with the expected
            hosts argument.

    Returns:
        An Elasticsearch client instance.

    Raises:
        ValueError: If the URL is empty or only whitespace.
        ImportError: If the elasticsearch package is not installed.
    """
    from elasticsearch import Elasticsearch  # type: ignore[import-not-found]

    url = os.getenv("MERKLELAKE_ES_URL", "http://localhost:9200").strip()
    if not url:
        raise ValueError("MERKLELAKE_ES_URL must not be empty")

    # Use explicit hosts argument so tests can inspect it easily.
    return Elasticsearch(hosts=[url])


def ensure_events_index(
    client: "Elasticsearch",
    index_name: str = "merklelake-events",
) -> None:
    """
    Ensure the events index exists in Elasticsearch with the required mapping.

    Target mapping (initial version):
        - tenant_id: keyword
        - block_id: keyword
        - leaf_idx: integer
        - root_hash_hex: keyword
        - ingest_ts: long
        - event: object (enabled)

    Algorithm:
        1. Call client.indices.exists(index=index_name).
        2. If True, return immediately (idempotent).
        3. If False, call client.indices.create(index=index_name, body=<mapping>).

    Raises:
        Any exception from client.indices.exists or client.indices.create.
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
                # Store the full original event for later inspection/search.
                "event": {"type": "object", "enabled": True},
            }
        }
    }

    client.indices.create(index=index_name, body=mapping)


def index_events_from_jsonl(
    header: BlockHeader,
    events_jsonl: str,
    client: "Elasticsearch",
    index_name: str = "merklelake-events",
) -> None:
    """
    Index each event from a sealed block into Elasticsearch.

    Input:
        - header: BlockHeader describing the sealed block.
        - events_jsonl: JSON Lines string (one canonical JSON object per line).
        - client: Elasticsearch client.
        - index_name: name of the events index.

    Document schema for each event:
        {
            "tenant_id": header.tenant_id,
            "block_id": header.block_id,
            "leaf_idx": <line index, starting at 0>,
            "root_hash_hex": header.root_hash_hex,
            "ingest_ts": <event["ingest_ts"]>,
            "event": <full parsed event object>
        }

    Algorithm:
        1. Ensure the events index exists by calling ensure_events_index().
        2. Split events_jsonl by newline to obtain lines; ignore empty lines.
        3. For each non-empty line with index i:
            a. Parse JSON into an event dict.
            b. Extract ingest_ts = event["ingest_ts"] and validate it's an int.
            c. Construct a document dict with the fields above.
        4. Build an Elasticsearch bulk operations list in the form:
                {"index": {"_index": index_name, "document": doc}}
                for each document.
        5. If there are no documents (e.g., all lines empty), return without
            calling bulk().
        6. Call client.bulk(operations=operations).

    Raises:
        ValueError: If events_jsonl is not a string, or if an event is missing
            ingest_ts or has a non-integer ingest_ts.
        json.JSONDecodeError: If any non-empty line is not valid JSON.
        Any exception from client.bulk.
    """
    if not isinstance(events_jsonl, str):
        raise ValueError("events_jsonl must be a string")

    ensure_events_index(client, index_name=index_name)

    lines = events_jsonl.splitlines()
    operations = []

    for leaf_idx, line in enumerate(lines):
        if not line.strip():
            # Ignore purely empty/whitespace lines.
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

        operations.append(
            {
                "index": {
                    "_index": index_name,
                    "document": doc,
                }
            }
        )

    # If there is nothing to index (e.g., empty JSONL), do nothing.
    if not operations:
        return

    client.bulk(operations=operations)

"""
Spec tests for merklelake.es helpers.

These tests define the expected behavior for Elasticsearch integration.
"""

from __future__ import annotations

import json
import sys
import types

import pytest

from merklelake.es import get_es_client, ensure_events_index, index_events_from_jsonl
from merklelake.proofs.chain import BlockHeader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeElasticsearchForGetClient:
    """Simple fake Elasticsearch class used to capture constructor arguments."""

    def __init__(self, *args, **kwargs):
        # We expect get_es_client to call Elasticsearch(hosts=[url]).
        self.args = args
        self.kwargs = kwargs
        self.hosts = kwargs.get("hosts")


def _install_fake_es_module(monkeypatch, fake_cls):
    """Install a fake 'elasticsearch' module exposing Elasticsearch=fake_cls."""
    fake_mod = types.ModuleType("elasticsearch")
    fake_mod.Elasticsearch = fake_cls
    monkeypatch.setitem(sys.modules, "elasticsearch", fake_mod)


# ---------------------------------------------------------------------------
# get_es_client specs
# ---------------------------------------------------------------------------


def test_get_es_client_uses_default_url_when_not_configured(monkeypatch):
    """
    SPEC:
        - When MERKLELAKE_ES_URL is not set, get_es_client() should:
            * Construct an Elasticsearch client configured for
              "http://localhost:9200".
        - No exceptions are raised.
    """
    # Remove env var if present.
    monkeypatch.delenv("MERKLELAKE_ES_URL", raising=False)

    # Install fake Elasticsearch module to capture constructor args.
    _install_fake_es_module(monkeypatch, _FakeElasticsearchForGetClient)

    client = get_es_client()

    assert isinstance(client, _FakeElasticsearchForGetClient)
    assert client.hosts == ["http://localhost:9200"]


# ---------------------------------------------------------------------------
# ensure_events_index specs
# ---------------------------------------------------------------------------


class _FakeIndices:
    """Fake .indices namespace for an Elasticsearch client."""

    def __init__(self, exists_return: bool):
        self._exists_return = exists_return
        self.exists_calls = []
        self.create_calls = []

    def exists(self, index: str) -> bool:
        self.exists_calls.append(index)
        return self._exists_return

    def create(self, index: str, body: dict) -> None:
        self.create_calls.append({"index": index, "body": body})


class _FakeEsClientForIndex:
    """Fake ES client with a controllable indices namespace."""

    def __init__(self, exists_return: bool):
        self.indices = _FakeIndices(exists_return=exists_return)


def test_ensure_events_index_idempotent_creation():
    """
    SPEC:
        - When the events index does not exist:
            * ensure_events_index(client, index_name) must call
              client.indices.create exactly once with a mapping that includes
              the fields:
                  tenant_id (keyword),
                  block_id (keyword),
                  leaf_idx (integer),
                  root_hash_hex (keyword),
                  ingest_ts (long),
                  event (object).
        - When the events index already exists:
            * ensure_events_index must NOT call indices.create.
    """
    index_name = "merklelake-events-test"

    # Case 1: index does not exist -> create should be called.
    client_missing = _FakeEsClientForIndex(exists_return=False)
    ensure_events_index(client_missing, index_name=index_name)

    # exists should be called once, create once.
    assert client_missing.indices.exists_calls == [index_name]
    assert len(client_missing.indices.create_calls) == 1

    create_call = client_missing.indices.create_calls[0]
    assert create_call["index"] == index_name
    body = create_call["body"]
    props = body["mappings"]["properties"]

    # Check required fields and their types.
    assert props["tenant_id"]["type"] == "keyword"
    assert props["block_id"]["type"] == "keyword"
    assert props["leaf_idx"]["type"] == "integer"
    assert props["root_hash_hex"]["type"] == "keyword"
    assert props["ingest_ts"]["type"] == "long"
    assert props["event"]["type"] == "object"

    # Case 2: index already exists -> create should not be called.
    client_exists = _FakeEsClientForIndex(exists_return=True)
    ensure_events_index(client_exists, index_name=index_name)

    assert client_exists.indices.exists_calls == [index_name]
    assert client_exists.indices.create_calls == []


# ---------------------------------------------------------------------------
# index_events_from_jsonl specs
# ---------------------------------------------------------------------------


class _FakeEsClientForBulk:
    """Fake ES client to test index_events_from_jsonl behavior."""

    def __init__(self, exists_return: bool = True):
        self.indices = _FakeIndices(exists_return=exists_return)
        self.bulk_calls = []

    def bulk(self, operations):
        # Record exactly what was passed.
        self.bulk_calls.append({"operations": operations})


def test_index_events_from_jsonl_builds_expected_documents_and_calls_bulk():
    """
    SPEC:
        - Given:
            * A small BlockHeader with known tenant_id, block_id, root_hash_hex.
            * events_jsonl with three lines (no trailing newline), each having
              an ingest_ts and an additional field.
          index_events_from_jsonl must:
            1. Call ensure_events_index(client, index_name).
            2. Construct exactly three documents with:
                - leaf_idx == line index (0, 1, 2).
                - tenant_id and block_id from header.
                - root_hash_hex from header.
                - ingest_ts matching the event value.
                - event field equal to the parsed JSON object.
            3. Call client.bulk once with an operations list corresponding to
               these documents.
    """
    # Header with known values.
    header = BlockHeader(
        block_id="block-1",
        tenant_id="tenant-A",
        ts_start=100,
        ts_end=200,
        root_hash_hex="r" * 64,
        prev_link_hash_hex="p" * 64,
        link_hash_hex="l" * 64,
    )

    # Three valid JSON lines, no trailing newline.
    events_jsonl = "\n".join(
        [
            '{"ingest_ts": 100, "msg": "alpha"}',
            '{"ingest_ts": 101, "msg": "beta"}',
            '{"ingest_ts": 102, "msg": "gamma"}',
        ]
    )

    fake_client = _FakeEsClientForBulk(exists_return=False)
    index_name = "merklelake-events-test"

    index_events_from_jsonl(
        header=header,
        events_jsonl=events_jsonl,
        client=fake_client,
        index_name=index_name,
    )

    # ensure_events_index should have checked/created the index once.
    assert fake_client.indices.exists_calls == [index_name]
    assert len(fake_client.indices.create_calls) == 1

    # bulk should be called exactly once.
    assert len(fake_client.bulk_calls) == 1
    operations = fake_client.bulk_calls[0]["operations"]

    # We expect exactly 3 operations, one per event.
    assert len(operations) == 3

    for i, op in enumerate(operations):
        assert "index" in op
        index_op = op["index"]

        assert index_op["_index"] == index_name
        doc = index_op["document"]

        # Basic fields.
        assert doc["tenant_id"] == header.tenant_id
        assert doc["block_id"] == header.block_id
        assert doc["root_hash_hex"] == header.root_hash_hex
        assert doc["leaf_idx"] == i

        # ingest_ts and event payload.
        event_obj = doc["event"]
        assert doc["ingest_ts"] == event_obj["ingest_ts"]
        assert doc["ingest_ts"] == 100 + i

        # The event field should be exactly the parsed JSON object.
        # Check a secondary field to be sure.
        if i == 0:
            assert event_obj["msg"] == "alpha"
        elif i == 1:
            assert event_obj["msg"] == "beta"
        else:
            assert event_obj["msg"] == "gamma"


def test_index_events_from_jsonl_raises_on_malformed_json_line():
    """
    SPEC:
        - If events_jsonl contains at least one line that is not valid JSON:
            * index_events_from_jsonl must raise an exception (e.g., JSONDecodeError
              or ValueError).
            * The client.bulk method should NOT be called, to avoid partial
              indexing of a corrupted batch.
    """
    header = BlockHeader(
        block_id="block-1",
        tenant_id="tenant-A",
        ts_start=100,
        ts_end=200,
        root_hash_hex="r" * 64,
        prev_link_hash_hex="p" * 64,
        link_hash_hex="l" * 64,
    )

    # First line valid, second line malformed.
    events_jsonl = "\n".join(
        [
            '{"ingest_ts": 100, "msg": "alpha"}',
            "not-json",
        ]
    )

    fake_client = _FakeEsClientForBulk(exists_return=False)
    index_name = "merklelake-events-test"

    with pytest.raises(Exception):
        index_events_from_jsonl(
            header=header,
            events_jsonl=events_jsonl,
            client=fake_client,
            index_name=index_name,
        )

    # ensure_events_index will still have been called.
    assert fake_client.indices.exists_calls == [index_name]
    # But bulk must never be invoked due to parse error.
    assert fake_client.bulk_calls == []

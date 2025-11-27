"""
Spec tests for merklelake.ingest.ingest_batch.

These tests ensure that ingest_batch orchestrates sealing, storage, and
indexing correctly, and that errors are propagated appropriately.
"""

from __future__ import annotations

import pytest

from merklelake import ingest as ingest_mod
from merklelake.proofs.chain import ZERO_LINK, BlockHeader


def test_ingest_batch_happy_path_calls_seal_storage_and_es_in_order(monkeypatch):
    """Happy path: seal, store, index, and return header/root_hash_hex."""
    events = [
        {"ingest_ts": 100, "msg": "alpha"},
        {"ingest_ts": 101, "msg": "beta"},
        {"ingest_ts": 102, "msg": "gamma"},
    ]
    tenant_id = "tenant-A"
    block_id = "block-1"

    # Dummy header returned by seal_block.
    dummy_header = BlockHeader(
        block_id=block_id,
        tenant_id=tenant_id,
        ts_start=100,
        ts_end=102,
        root_hash_hex="r" * 64,
        prev_link_hash_hex=ZERO_LINK,
        link_hash_hex="l" * 64,
    )
    dummy_jsonl = "line0\nline1\nline2"
    dummy_levels = [["dummy-level"]]

    seal_calls = {}

    def fake_seal_block(
        *,
        events: list,
        tenant_id: str,
        block_id: str,
        prev_link_hash_hex: str = ZERO_LINK,
    ):
        seal_calls["called"] = True
        seal_calls["events"] = events
        seal_calls["tenant_id"] = tenant_id
        seal_calls["block_id"] = block_id
        seal_calls["prev_link_hash_hex"] = prev_link_hash_hex
        return dummy_header, dummy_jsonl, dummy_levels

    monkeypatch.setattr(ingest_mod, "seal_block", fake_seal_block)

    class FakeStorage:
        def __init__(self):
            self.put_calls = []

        def put_block(self, header, events_jsonl):
            self.put_calls.append((header, events_jsonl))

    fake_storage = FakeStorage()

    class FakeEsClient:
        pass

    fake_es_client = FakeEsClient()
    es_calls = {"get_client_called": 0, "index_calls": []}

    def fake_get_es_client():
        es_calls["get_client_called"] += 1
        return fake_es_client

    def fake_index_events_from_jsonl(
        *, header, events_jsonl, client, index_name="merklelake-events"
    ):
        es_calls["index_calls"].append(
            {
                "header": header,
                "events_jsonl": events_jsonl,
                "client": client,
                "index_name": index_name,
            }
        )

    monkeypatch.setattr(ingest_mod, "get_es_client", fake_get_es_client)
    monkeypatch.setattr(
        ingest_mod, "index_events_from_jsonl", fake_index_events_from_jsonl
    )

    # Call ingest_batch with injected storage.
    header, root_hash_hex = ingest_mod.ingest_batch(
        events=events,
        tenant_id=tenant_id,
        block_id=block_id,
        storage=fake_storage,
    )

    # seal_block assertions.
    assert seal_calls.get("called") is True
    assert seal_calls["events"] == events
    assert seal_calls["tenant_id"] == tenant_id
    assert seal_calls["block_id"] == block_id
    assert seal_calls["prev_link_hash_hex"] == ZERO_LINK

    # storage.put_block assertions.
    assert len(fake_storage.put_calls) == 1
    stored_header, stored_jsonl = fake_storage.put_calls[0]
    assert stored_header is dummy_header
    assert stored_jsonl == dummy_jsonl

    # ES indexing assertions.
    assert es_calls["get_client_called"] == 1
    assert len(es_calls["index_calls"]) == 1
    index_call = es_calls["index_calls"][0]
    assert index_call["header"] is dummy_header
    assert index_call["events_jsonl"] == dummy_jsonl
    assert index_call["client"] is fake_es_client

    # Return value assertions.
    assert header is dummy_header
    assert root_hash_hex == dummy_header.root_hash_hex


def test_ingest_batch_propagates_seal_block_errors(monkeypatch):
    """If seal_block fails, propagate and do not call storage or ES."""

    def fake_seal_block(*args, **kwargs):
        raise ValueError("seal failed")

    monkeypatch.setattr(ingest_mod, "seal_block", fake_seal_block)

    class FakeStorage:
        def __init__(self):
            self.put_calls = []

        def put_block(self, header, events_jsonl):
            self.put_calls.append((header, events_jsonl))

    fake_storage = FakeStorage()

    es_calls = {"index_called": False, "get_client_called": False}

    def fake_get_es_client():
        es_calls["get_client_called"] = True
        return object()

    def fake_index_events_from_jsonl(*args, **kwargs):
        es_calls["index_called"] = True

    monkeypatch.setattr(ingest_mod, "get_es_client", fake_get_es_client)
    monkeypatch.setattr(
        ingest_mod, "index_events_from_jsonl", fake_index_events_from_jsonl
    )

    with pytest.raises(ValueError, match="seal failed"):
        ingest_mod.ingest_batch(
            events=[{"ingest_ts": 100}],
            tenant_id="tenant-A",
            block_id="block-1",
            storage=fake_storage,
        )

    # storage and ES must not be touched.
    assert fake_storage.put_calls == []
    assert es_calls["get_client_called"] is False
    assert es_calls["index_called"] is False


def test_ingest_batch_propagates_storage_errors(monkeypatch):
    """If storage.put_block fails, propagate and do not call ES indexing."""
    # Stub seal_block to succeed.
    dummy_header = BlockHeader(
        block_id="block-1",
        tenant_id="tenant-A",
        ts_start=100,
        ts_end=102,
        root_hash_hex="r" * 64,
        prev_link_hash_hex=ZERO_LINK,
        link_hash_hex="l" * 64,
    )
    dummy_jsonl = "line0\nline1"

    seal_calls = {"called": False}

    def fake_seal_block(*, events, tenant_id, block_id, prev_link_hash_hex=ZERO_LINK):
        seal_calls["called"] = True
        return dummy_header, dummy_jsonl, [["dummy"]]

    monkeypatch.setattr(ingest_mod, "seal_block", fake_seal_block)

    class FakeStorage:
        def __init__(self):
            self.put_calls = 0

        def put_block(self, header, events_jsonl):
            self.put_calls += 1
            raise RuntimeError("storage failure")

    fake_storage = FakeStorage()

    es_calls = {"get_client_called": False, "index_called": False}

    def fake_get_es_client():
        es_calls["get_client_called"] = True
        return object()

    def fake_index_events_from_jsonl(*args, **kwargs):
        es_calls["index_called"] = True

    monkeypatch.setattr(ingest_mod, "get_es_client", fake_get_es_client)
    monkeypatch.setattr(
        ingest_mod, "index_events_from_jsonl", fake_index_events_from_jsonl
    )

    with pytest.raises(RuntimeError, match="storage failure"):
        ingest_mod.ingest_batch(
            events=[{"ingest_ts": 100}],
            tenant_id="tenant-A",
            block_id="block-1",
            storage=fake_storage,
        )

    assert seal_calls["called"] is True
    assert fake_storage.put_calls == 1
    # ES should not be touched if storage fails.
    assert es_calls["get_client_called"] is False
    assert es_calls["index_called"] is False


def test_ingest_batch_propagates_indexing_errors(monkeypatch):
    """If indexing fails, propagate but still seal and store."""
    dummy_header = BlockHeader(
        block_id="block-1",
        tenant_id="tenant-A",
        ts_start=100,
        ts_end=102,
        root_hash_hex="r" * 64,
        prev_link_hash_hex=ZERO_LINK,
        link_hash_hex="l" * 64,
    )
    dummy_jsonl = "line0\nline1"

    seal_calls = {"called": False}

    def fake_seal_block(*, events, tenant_id, block_id, prev_link_hash_hex=ZERO_LINK):
        seal_calls["called"] = True
        return dummy_header, dummy_jsonl, [["dummy"]]

    monkeypatch.setattr(ingest_mod, "seal_block", fake_seal_block)

    class FakeStorage:
        def __init__(self):
            self.put_calls = []

        def put_block(self, header, events_jsonl):
            self.put_calls.append((header, events_jsonl))

    fake_storage = FakeStorage()

    class IndexingError(RuntimeError):
        pass

    es_calls = {"get_client_called": 0, "index_called": 0}

    class FakeEsClient:
        pass

    fake_es_client = FakeEsClient()

    def fake_get_es_client():
        es_calls["get_client_called"] += 1
        return fake_es_client

    def fake_index_events_from_jsonl(
        *, header, events_jsonl, client, index_name="merklelake-events"
    ):
        es_calls["index_called"] += 1
        raise IndexingError("indexing failure")

    monkeypatch.setattr(ingest_mod, "get_es_client", fake_get_es_client)
    monkeypatch.setattr(
        ingest_mod, "index_events_from_jsonl", fake_index_events_from_jsonl
    )

    with pytest.raises(IndexingError, match="indexing failure"):
        ingest_mod.ingest_batch(
            events=[{"ingest_ts": 100}],
            tenant_id="tenant-A",
            block_id="block-1",
            storage=fake_storage,
        )

    # seal_block + storage must have been called once.
    assert seal_calls["called"] is True
    assert len(fake_storage.put_calls) == 1
    stored_header, stored_jsonl = fake_storage.put_calls[0]
    assert stored_header is dummy_header
    assert stored_jsonl == dummy_jsonl

    # ES get_client and index must each have been called once.
    assert es_calls["get_client_called"] == 1
    assert es_calls["index_called"] == 1

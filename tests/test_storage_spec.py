"""
Spec tests for merklelake.storage.BlockStorage and get_minio_client.

These tests define the required behaviors of the storage layer using
high-level descriptions. Implementations should satisfy these specs.
"""

from __future__ import annotations

import io
import json
import sys
import types

import pytest

from merklelake.storage import get_minio_client, BlockStorage, BlockStorageConfig
from merklelake.proofs.chain import BlockHeader


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeMinioForGetClient:
    """Simple fake Minio class used to capture constructor arguments."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.secure = secure


def _install_fake_minio_module(monkeypatch, fake_cls):
    """Install a fake 'minio' module into sys.modules exposing Minio=fake_cls."""
    fake_mod = types.ModuleType("minio")
    fake_mod.Minio = fake_cls
    monkeypatch.setitem(sys.modules, "minio", fake_mod)


# ---------------------------------------------------------------------------
# get_minio_client specs
# ---------------------------------------------------------------------------


def test_get_minio_client_uses_defaults_when_env_missing(monkeypatch):
    """
    SPEC:
        - When no MERKLELAKE_* env vars are set:
            * get_minio_client() returns a Minio client configured with:
                endpoint == "localhost:9000"
                access_key == "minioadmin"
                secret_key == "minioadmin"
                secure == False
        - No exceptions are raised.
        - This test will monkeypatch os.environ to a minimal empty mapping.
    """
    # Clear relevant env vars.
    for var in (
        "MERKLELAKE_MINIO_ENDPOINT",
        "MERKLELAKE_MINIO_ACCESS_KEY",
        "MERKLELAKE_MINIO_SECRET_KEY",
        "MERKLELAKE_MINIO_SECURE",
    ):
        monkeypatch.delenv(var, raising=False)

    # Install fake Minio class.
    _install_fake_minio_module(monkeypatch, _FakeMinioForGetClient)

    # Call get_minio_client and inspect configuration.
    client = get_minio_client()

    assert isinstance(client, _FakeMinioForGetClient)
    assert client.endpoint == "localhost:9000"
    assert client.access_key == "minioadmin"
    assert client.secret_key == "minioadmin"
    assert client.secure is False


def test_get_minio_client_respects_custom_env_settings(monkeypatch):
    """
    SPEC:
        - When MERKLELAKE_MINIO_ENDPOINT / ACCESS_KEY / SECRET_KEY / SECURE
          are set, get_minio_client() should:
            * Use the provided values.
            * Interpret MERKLELAKE_MINIO_SECURE case-insensitively as a boolean.
        - Example:
            MERKLELAKE_MINIO_ENDPOINT="minio:9000"
            MERKLELAKE_MINIO_SECURE="TRUE"
          => secure == True
    """
    # Install fake Minio class.
    _install_fake_minio_module(monkeypatch, _FakeMinioForGetClient)

    # Set custom env vars.
    monkeypatch.setenv("MERKLELAKE_MINIO_ENDPOINT", "minio:9000")
    monkeypatch.setenv("MERKLELAKE_MINIO_ACCESS_KEY", "custom_access")
    monkeypatch.setenv("MERKLELAKE_MINIO_SECRET_KEY", "custom_secret")
    monkeypatch.setenv("MERKLELAKE_MINIO_SECURE", "TRUE")

    client = get_minio_client()

    assert isinstance(client, _FakeMinioForGetClient)
    assert client.endpoint == "minio:9000"
    assert client.access_key == "custom_access"
    assert client.secret_key == "custom_secret"
    assert client.secure is True


# ---------------------------------------------------------------------------
# BlockStorage.ensure_buckets specs
# ---------------------------------------------------------------------------


class _FakeMinioForBuckets:
    """Fake Minio client to test ensure_buckets behavior."""

    def __init__(self):
        self._existing = set()
        self.bucket_exists_calls = []
        self.make_bucket_calls = []

    def bucket_exists(self, name: str) -> bool:
        self.bucket_exists_calls.append(name)
        return name in self._existing

    def make_bucket(self, name: str) -> None:
        self.make_bucket_calls.append(name)
        self._existing.add(name)


def test_blockstorage_ensure_buckets_creates_missing_buckets():
    """
    SPEC:
        - Given a fake Minio client where:
            bucket_exists("blocks") -> False
            bucket_exists("events") -> False
          BlockStorage.ensure_buckets() must:
            * call make_bucket("blocks") exactly once
            * call make_bucket("events") exactly once
    """
    fake_client = _FakeMinioForBuckets()
    config = BlockStorageConfig(blocks_bucket="blocks", events_bucket="events")
    storage = BlockStorage(fake_client, config)

    # First call: both buckets missing, so make_bucket should be called for each.
    storage.ensure_buckets()

    assert fake_client.make_bucket_calls.count("blocks") == 1
    assert fake_client.make_bucket_calls.count("events") == 1

    # Second call: buckets now exist, so no additional make_bucket calls.
    storage.ensure_buckets()

    assert fake_client.make_bucket_calls.count("blocks") == 1
    assert fake_client.make_bucket_calls.count("events") == 1


# ---------------------------------------------------------------------------
# BlockStorage.put_block specs
# ---------------------------------------------------------------------------


class _RecordingMinioClient:
    """Fake Minio client to record put_object calls for put_block tests."""

    def __init__(self):
        self.buckets = set()
        self.put_calls = (
            []
        )  # list of dicts with bucket_name, object_name, body, content_type

    # Bucket management -----------------------------------------------------

    def bucket_exists(self, name: str) -> bool:
        return name in self.buckets

    def make_bucket(self, name: str) -> None:
        self.buckets.add(name)

    # Object writing --------------------------------------------------------

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: io.IOBase,
        length: int,
        content_type: str | None = None,
    ) -> None:
        body = data.read()
        # Sanity check: data length matches argument.
        assert len(body) == length
        self.put_calls.append(
            {
                "bucket_name": bucket_name,
                "object_name": object_name,
                "body": body,
                "content_type": content_type,
            }
        )


def test_blockstorage_put_block_writes_header_and_events_objects():
    """
    SPEC:
        - When put_block(header, events_jsonl) is called:
            * ensure_buckets() is invoked.
            * The client receives two put_object-like calls:
                - one to the blocks bucket with key:
                    f"{tenant_id}/{block_id}/block.json"
                - one to the events bucket with key:
                    f"{tenant_id}/{block_id}/events.jsonl"
            * The header payload is a JSON object encoding exactly the
              BlockHeader fields (block_id, tenant_id, ts_start, ts_end,
              root_hash_hex, prev_link_hash_hex, link_hash_hex).
            * The events payload bytes equal events_jsonl.encode("utf-8").
    """
    fake_client = _RecordingMinioClient()
    config = BlockStorageConfig(
        blocks_bucket="blocks-bucket", events_bucket="events-bucket"
    )
    storage = BlockStorage(fake_client, config)

    header = BlockHeader(
        block_id="block-1",
        tenant_id="tenant-A",
        ts_start=100,
        ts_end=102,
        root_hash_hex="r" * 64,
        prev_link_hash_hex="p" * 64,
        link_hash_hex="l" * 64,
    )
    events_jsonl = "line1\nline2"

    storage.put_block(header, events_jsonl)

    # ensure_buckets should have created both buckets.
    assert "blocks-bucket" in fake_client.buckets
    assert "events-bucket" in fake_client.buckets

    # There should be exactly two put_object calls.
    assert len(fake_client.put_calls) == 2

    # Partition calls by bucket.
    blocks_calls = [
        c for c in fake_client.put_calls if c["bucket_name"] == "blocks-bucket"
    ]
    events_calls = [
        c for c in fake_client.put_calls if c["bucket_name"] == "events-bucket"
    ]

    assert len(blocks_calls) == 1
    assert len(events_calls) == 1

    header_call = blocks_calls[0]
    events_call = events_calls[0]

    # Keys must follow the expected pattern.
    expected_prefix = f"{header.tenant_id}/{header.block_id}"
    assert header_call["object_name"] == f"{expected_prefix}/block.json"
    assert events_call["object_name"] == f"{expected_prefix}/events.jsonl"

    # Header JSON must match the BlockHeader fields exactly.
    header_body = header_call["body"].decode("utf-8")
    header_json = json.loads(header_body)

    assert set(header_json.keys()) == {
        "block_id",
        "tenant_id",
        "ts_start",
        "ts_end",
        "root_hash_hex",
        "prev_link_hash_hex",
        "link_hash_hex",
    }
    assert header_json["block_id"] == header.block_id
    assert header_json["tenant_id"] == header.tenant_id
    assert header_json["ts_start"] == header.ts_start
    assert header_json["ts_end"] == header.ts_end
    assert header_json["root_hash_hex"] == header.root_hash_hex
    assert header_json["prev_link_hash_hex"] == header.prev_link_hash_hex
    assert header_json["link_hash_hex"] == header.link_hash_hex

    # Events payload must equal events_jsonl encoded as UTF-8.
    events_body = events_call["body"]
    assert events_body == events_jsonl.encode("utf-8")

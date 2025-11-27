"""
Storage layer for MerkleLake blocks (object storage).

This module defines:

    - get_minio_client: construct a MinIO client from env vars.
    - BlockStorage: high-level API to store and retrieve blocks.

Design notes:
    - We treat MinIO as S3-compatible object storage.
    - We separate "blocks" (headers) from "events" (JSONL payloads) into
        distinct buckets to match the storage layout docs.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - type-checking only
    from minio import Minio

from .proofs.chain import BlockHeader


def _parse_secure_flag(value: str) -> bool:
    """Parse MERKLELAKE_MINIO_SECURE string into a boolean.

    Accepted truthy values (case-insensitive): "true", "1", "yes", "y", "on".
    Accepted falsy values: "false", "0", "no", "n", "off", "".

    Args:
        value: String flag from the environment.

    Returns:
        True if the flag is interpreted as secure, False otherwise.

    Raises:
        ValueError: If the value cannot be interpreted as a boolean.
    """
    v = value.strip().lower()
    if v in ("true", "1", "yes", "y", "on"):
        return True
    if v in ("false", "0", "no", "n", "off", ""):
        return False
    raise ValueError(f"Invalid MERKLELAKE_MINIO_SECURE value: {value!r}")


def get_minio_client() -> "Minio":
    """Construct a MinIO client configured from environment variables.

    Environment:
        MERKLELAKE_MINIO_ENDPOINT: Endpoint, default "localhost:9000".
        MERKLELAKE_MINIO_ACCESS_KEY: Access key, default "minioadmin".
        MERKLELAKE_MINIO_SECRET_KEY: Secret key, default "minioadmin".
        MERKLELAKE_MINIO_SECURE: "true"/"false" etc., default "false".

    Returns:
        A configured Minio client instance.

    Raises:
        ValueError: If the endpoint is missing/blank or the secure flag is invalid.
        ImportError: If the minio package is not installed.
    """
    from minio import Minio  # type: ignore[import-not-found]

    endpoint = os.getenv("MERKLELAKE_MINIO_ENDPOINT", "localhost:9000").strip()
    access_key = os.getenv("MERKLELAKE_MINIO_ACCESS_KEY", "minioadmin")
    secret_key = os.getenv("MERKLELAKE_MINIO_SECRET_KEY", "minioadmin")
    secure_str = os.getenv("MERKLELAKE_MINIO_SECURE", "false")

    if not endpoint:
        raise ValueError("MERKLELAKE_MINIO_ENDPOINT must not be empty")

    secure = _parse_secure_flag(secure_str)

    return Minio(
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )


@dataclass
class BlockStorageConfig:
    """Configuration for BlockStorage.

    Attributes:
        blocks_bucket: Bucket name for block headers (block.json).
        events_bucket: Bucket name for event payloads (events.jsonl).
    """

    blocks_bucket: str
    events_bucket: str


class BlockStorage:
    """High-level API for storing MerkleLake blocks in MinIO.

    This class manages bucket creation and object naming but does not
    understand Merkle trees or proofs.
    """

    def __init__(
        self,
        client: "Minio",
        config: BlockStorageConfig,
    ) -> None:
        """Initialize the storage wrapper.

        Args:
            client: A Minio client instance (or test double).
            config: Storage configuration with bucket names.
        """
        self._client = client
        self._config = config

    @property
    def client(self) -> "Minio":
        """Return the underlying MinIO client.

        Returns:
            The Minio client passed at initialization.
        """
        return self._client

    @property
    def config(self) -> BlockStorageConfig:
        """Return the storage configuration.

        Returns:
            The BlockStorageConfig used by this instance.
        """
        return self._config

    def ensure_buckets(self) -> None:
        """Ensure the configured buckets exist in MinIO.

        For each bucket in the configuration, this method checks
        existence and creates the bucket if it does not yet exist.

        Raises:
            Any exception raised by the underlying Minio client.
        """
        for bucket in (self._config.blocks_bucket, self._config.events_bucket):
            exists = self._client.bucket_exists(bucket)
            if not exists:
                self._client.make_bucket(bucket)

    def put_block(self, header: BlockHeader, events_jsonl: str) -> None:
        """Store a sealed block (header + events JSONL) in object storage.

        This writes the header JSON and events JSONL to separate buckets
        using a fixed key layout: `<tenant_id>/<block_id>/block.json` and
        `<tenant_id>/<block_id>/events.jsonl`.

        Args:
            header: BlockHeader describing the sealed block.
            events_jsonl: JSON Lines text for the block's events.

        Raises:
            ValueError: If tenant_id or block_id are empty or if events_jsonl
                is not a string.
            Any exception raised by the underlying Minio client.
        """
        tenant_id = getattr(header, "tenant_id", None)
        block_id = getattr(header, "block_id", None)

        if not isinstance(tenant_id, str) or not tenant_id:
            raise ValueError("header.tenant_id must be a non-empty string")
        if not isinstance(block_id, str) or not block_id:
            raise ValueError("header.block_id must be a non-empty string")

        if not isinstance(events_jsonl, str):
            raise ValueError("events_jsonl must be a string")

        header_key = f"{tenant_id}/{block_id}/block.json"
        events_key = f"{tenant_id}/{block_id}/events.jsonl"

        header_dict = asdict(header)
        header_json = json.dumps(header_dict, sort_keys=True, separators=(",", ":"))
        header_bytes = header_json.encode("utf-8")

        events_bytes = events_jsonl.encode("utf-8")

        self.ensure_buckets()

        self._client.put_object(
            bucket_name=self._config.blocks_bucket,
            object_name=header_key,
            data=io.BytesIO(header_bytes),
            length=len(header_bytes),
            content_type="application/json",
        )

        self._client.put_object(
            bucket_name=self._config.events_bucket,
            object_name=events_key,
            data=io.BytesIO(events_bytes),
            length=len(events_bytes),
            content_type="application/json",
        )

    # Optional future methods (for proof/api layer) can be added later:
    # - get_block_header(tenant_id, block_id) -> BlockHeader
    # - get_events_jsonl(tenant_id, block_id) -> str

"""
Storage layer for MerkleLake blocks (object storage).

This module provides helpers to construct a MinIO client from environment
variables and a ``BlockStorage`` wrapper for reading and writing sealed blocks.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from minio import Minio

from .proofs.chain import BlockHeader


def _parse_secure_flag(value: str) -> bool:
    """Converts a MERKLELAKE_MINIO_SECURE value to a boolean."""
    v = value.strip().lower()
    if v in ("true", "1", "yes", "y", "on"):
        return True
    if v in ("false", "0", "no", "n", "off", ""):
        return False
    raise ValueError(f"Invalid MERKLELAKE_MINIO_SECURE value: {value!r}")


def get_minio_client() -> "Minio":
    """Creates a MinIO client configured from environment variables."""
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
    """Configuration for ``BlockStorage``.

    Attributes:
        blocks_bucket: Bucket name for block headers (``block.json``).
        events_bucket: Bucket name for event payloads (``events.jsonl``).
        public_bucket: Bucket name for public checkpoints.
    """

    blocks_bucket: str
    events_bucket: str
    public_bucket: str = "merklelake-public"


class BlockStorage:
    """High-level API for storing MerkleLake blocks in MinIO."""

    def __init__(
        self,
        client: "Minio",
        config: BlockStorageConfig,
    ) -> None:
        self._client = client
        self._config = config

    @property
    def client(self) -> "Minio":
        return self._client

    @property
    def config(self) -> BlockStorageConfig:
        return self._config

    def ensure_buckets(self) -> None:
        """Ensures that the configured buckets exist in MinIO."""
        buckets = [
            self._config.blocks_bucket,
            self._config.events_bucket,
            self._config.public_bucket,
        ]
        for bucket in buckets:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)

    def put_block(self, header: BlockHeader, events_jsonl: str) -> None:
        """Stores a sealed block (header and events) in object storage."""
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

    def get_block_header(self, tenant_id: str, block_id: str) -> BlockHeader:
        """Retrieves the metadata file (``block.json``) for a specific block."""
        key = f"{tenant_id}/{block_id}/block.json"
        try:
            response = self._client.get_object(self._config.blocks_bucket, key)
            try:
                data = response.read()
                header_dict = json.loads(data)
                return BlockHeader(**header_dict)
            finally:
                response.close()
                response.release_conn()
        except Exception as e:
            raise ValueError(f"Failed to fetch block header for {key}") from e

    def get_events_jsonl(self, tenant_id: str, block_id: str) -> str:
        """Retrieves the raw event data (``events.jsonl``) for a block."""
        key = f"{tenant_id}/{block_id}/events.jsonl"
        try:
            response = self._client.get_object(self._config.events_bucket, key)
            try:
                data = response.read()
                return data.decode("utf-8")
            finally:
                response.close()
                response.release_conn()
        except Exception as e:
            raise ValueError(f"Failed to fetch events for {key}") from e

    def get_checkpoint(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves the latest checkpoint for a tenant.

        Returns:
            The checkpoint dict if found, or None if no checkpoint exists.
        """
        key = f"checkpoints/{tenant_id}/latest.json"
        try:
            response = self._client.get_object(self._config.public_bucket, key)
            try:
                data = response.read()
                return json.loads(data)
            finally:
                response.close()
                response.release_conn()
        except Exception:
            # If the object is not found (e.g. 404), return None
            return None

    def put_checkpoint(
        self, tenant_id: str, checkpoint_data: Dict[str, Any], history_key: str
    ) -> None:
        """Writes a checkpoint to both latest.json and a history path.

        Args:
            tenant_id: The tenant identifier.
            checkpoint_data: The dictionary content of the checkpoint.
            history_key: The path for the immutable history snapshot
                        (e.g., checkpoints/{tenant}/history/.../timestamp.json).
        """
        self.ensure_buckets()

        payload_bytes = json.dumps(
            checkpoint_data, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

        # 1. Write immutable history
        self._client.put_object(
            bucket_name=self._config.public_bucket,
            object_name=history_key,
            data=io.BytesIO(payload_bytes),
            length=len(payload_bytes),
            content_type="application/json",
        )

        # 2. Update mutable pointer (latest.json)
        latest_key = f"checkpoints/{tenant_id}/latest.json"
        self._client.put_object(
            bucket_name=self._config.public_bucket,
            object_name=latest_key,
            data=io.BytesIO(payload_bytes),
            length=len(payload_bytes),
            content_type="application/json",
        )

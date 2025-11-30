"""
Storage layer for MerkleLake blocks (object storage).

This module provides helpers to construct a MinIO client from environment
variables and a ``BlockStorage`` wrapper for reading and writing sealed blocks.

Typical usage example:
    client = get_minio_client()
    config = BlockStorageConfig(blocks_bucket="blocks", events_bucket="events")
    storage = BlockStorage(client=client, config=config)
    storage.put_block(header, events_jsonl)
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from minio import Minio

from .proofs.chain import BlockHeader


def _parse_secure_flag(value: str) -> bool:
    """Converts a MERKLELAKE_MINIO_SECURE value to a boolean.

    Accepted truthy values (case-insensitive) are:
    "true", "1", "yes", "y", "on".

    Accepted falsy values are:
    "false", "0", "no", "n", "off", and the empty string.

    Args:
        value: Raw string flag from the environment.

    Returns:
        True if the flag is interpreted as secure, False otherwise.

    Raises:
        ValueError: If the value cannot be interpreted as a boolean flag.
    """
    v = value.strip().lower()
    if v in ("true", "1", "yes", "y", "on"):
        return True
    if v in ("false", "0", "no", "n", "off", ""):
        return False
    raise ValueError(f"Invalid MERKLELAKE_MINIO_SECURE value: {value!r}")


def get_minio_client() -> "Minio":
    """Creates a MinIO client configured from environment variables.

    The following environment variables are consulted:

    * MERKLELAKE_MINIO_ENDPOINT: MinIO endpoint (default "localhost:9000").
    * MERKLELAKE_MINIO_ACCESS_KEY: Access key (default "minioadmin").
    * MERKLELAKE_MINIO_SECRET_KEY: Secret key (default "minioadmin").
    * MERKLELAKE_MINIO_SECURE: TLS flag such as "true" or "false"
        (default "false").

    Returns:
        A configured ``Minio`` client instance.

    Raises:
        ValueError: If the endpoint is empty or the secure flag is invalid.
        ImportError: If the ``minio`` package is not installed.
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
    """Configuration for ``BlockStorage``.

    Attributes:
        blocks_bucket: Bucket name for block headers (``block.json``).
        events_bucket: Bucket name for event payloads (``events.jsonl``).
    """

    blocks_bucket: str
    events_bucket: str


class BlockStorage:
    """High-level API for storing MerkleLake blocks in MinIO.

    This wrapper manages bucket creation and object naming. It does not
    implement Merkle trees, proofs, or any cryptographic logic.
    """

    def __init__(
        self,
        client: "Minio",
        config: BlockStorageConfig,
    ) -> None:
        """Initializes ``BlockStorage``.

        Args:
            client: A ``Minio`` client instance (or a compatible test double).
            config: Storage configuration specifying bucket names.
        """
        self._client = client
        self._config = config

    @property
    def client(self) -> "Minio":
        """Returns the underlying MinIO client.

        Returns:
            The ``Minio`` client passed at initialization.
        """
        return self._client

    @property
    def config(self) -> BlockStorageConfig:
        """Returns the storage configuration.

        Returns:
            The ``BlockStorageConfig`` used by this instance.
        """
        return self._config

    def ensure_buckets(self) -> None:
        """Ensures that the configured buckets exist in MinIO.

        For each bucket in the configuration, this method checks whether the
        bucket exists and creates it if it does not.

        Raises:
            Any exception raised by the underlying MinIO client.
        """
        for bucket in (self._config.blocks_bucket, self._config.events_bucket):
            exists = self._client.bucket_exists(bucket)
            if not exists:
                self._client.make_bucket(bucket)

    def put_block(self, header: BlockHeader, events_jsonl: str) -> None:
        """Stores a sealed block (header and events) in object storage.

        The header JSON and events JSONL are written to separate buckets using
        the following key layout:

        * ``<tenant_id>/<block_id>/block.json``
        * ``<tenant_id>/<block_id>/events.jsonl``

        Args:
            header: Block header describing the sealed block.
            events_jsonl: JSON Lines text containing the block's events.

        Raises:
            ValueError: If ``tenant_id`` or ``block_id`` on the header are
                missing or empty, or if ``events_jsonl`` is not a string.
            Any exception raised by the underlying MinIO client.
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

    def get_block_header(self, tenant_id: str, block_id: str) -> BlockHeader:
        """Retrieves the metadata file (``block.json``) for a specific block.

        Args:
            tenant_id: Tenant identifier.
            block_id: Block identifier.

        Returns:
            A ``BlockHeader`` parsed from the stored ``block.json`` file.

        Raises:
            ValueError: If the header object cannot be fetched or parsed.
        """
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
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Failed to fetch block header for {key}") from e

    def get_events_jsonl(self, tenant_id: str, block_id: str) -> str:
        """Retrieves the raw event data (``events.jsonl``) for a block.

        Args:
            tenant_id: Tenant identifier.
            block_id: Block identifier.

        Returns:
            A JSON Lines string containing all events in the block.

        Raises:
            ValueError: If the events file cannot be fetched.
        """
        key = f"{tenant_id}/{block_id}/events.jsonl"
        try:
            response = self._client.get_object(self._config.events_bucket, key)
            try:
                data = response.read()
                return data.decode("utf-8")
            finally:
                response.close()
                response.release_conn()
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Failed to fetch events for {key}") from e

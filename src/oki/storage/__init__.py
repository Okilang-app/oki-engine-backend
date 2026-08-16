"""Oki storage layer."""

from oki.storage.protocol import ObjectStore
from oki.storage.s3 import S3ObjectStore

__all__ = ["ObjectStore", "S3ObjectStore"]

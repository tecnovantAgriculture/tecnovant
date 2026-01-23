from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import boto3


class StorageBackend(ABC):
    @abstractmethod
    def read_bytes(self, uri: str) -> bytes:
        raise NotImplementedError


@dataclass
class LocalStorage(StorageBackend):
    base_dir: Optional[Path] = None

    def read_bytes(self, uri: str) -> bytes:
        path = Path(uri)
        if self.base_dir is not None:
            path = (self.base_dir / path).resolve()
            if not str(path).startswith(str(self.base_dir.resolve())):
                raise PermissionError("Path traversal detected.")
        with open(path, "rb") as f:
            return f.read()


@dataclass
class S3Storage(StorageBackend):
    bucket: Optional[str] = None
    client: any = None

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = boto3.client(
                "s3",
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                region_name=os.getenv("AWS_REGION"),
            )

    def _parse(self, uri: str) -> Tuple[str, str]:
        if uri.startswith("s3://"):
            _, _, rest = uri.partition("s3://")
            bkt, _, key = rest.partition("/")
            return bkt, key
        if not self.bucket:
            raise ValueError("Bucket is required for S3 paths without s3:// prefix.")
        return self.bucket, uri

    def read_bytes(self, uri: str) -> bytes:
        bucket, key = self._parse(uri)
        obj = self.client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()

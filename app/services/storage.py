"""Tiny storage abstraction. Local fs or S3."""
from __future__ import annotations
from pathlib import Path
from app.core.config import get_settings


class Storage:
    def save(self, key: str, data: bytes) -> str:
        raise NotImplementedError

    def path(self, key: str) -> str:
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return str(p)

    def path(self, key: str) -> str:
        return str(self.root / key)


class S3Storage(Storage):
    def __init__(self, bucket: str, **kwargs):
        import boto3
        self.bucket = bucket
        self.client = boto3.client("s3", **kwargs)

    def save(self, key: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return f"s3://{self.bucket}/{key}"

    def path(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"


def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage(
            bucket=s.s3_bucket,
            endpoint_url=s.s3_endpoint_url or None,
            aws_access_key_id=s.s3_access_key or None,
            aws_secret_access_key=s.s3_secret_key or None,
        )
    return LocalStorage(s.storage_local_dir)

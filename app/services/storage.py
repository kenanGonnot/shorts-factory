"""Tiny storage abstraction. Local fs or S3.

Every tool that persists artifacts uses :class:`Storage`. The subtitle
stage also needs to *read* previously-persisted assets so ``ffmpeg`` can
consume them locally -- that is what :meth:`Storage.stage_local` is
for: a passthrough on local disk, a download-to-temp on S3.
"""
from __future__ import annotations

import os
import tempfile
from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class StagedAsset:
    """A locally-available copy of a persisted asset.

    ``local_path`` is always a real filesystem path readable by
    ``ffmpeg``. ``cleanup`` must be called when the consumer is done; it
    is a no-op for assets that already lived on local disk.
    """

    local_path: str
    _cleanup_dir: str | None = None

    def cleanup(self) -> None:
        if self._cleanup_dir and os.path.isdir(self._cleanup_dir):
            # Best-effort cleanup; never raise from a cleanup path.
            import shutil
            shutil.rmtree(self._cleanup_dir, ignore_errors=True)

    def __enter__(self) -> "StagedAsset":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()


class Storage:
    @abstractmethod
    def save(self, key: str, data: bytes) -> str:
        ...

    @abstractmethod
    def path(self, key: str) -> str:
        ...

    @abstractmethod
    def stage_local(self, key_or_path: str) -> StagedAsset:
        """Materialize an asset to a local filesystem path.

        ``key_or_path`` may be either a storage key (``"{job_id}/file"``)
        or the value returned by :meth:`save` / :meth:`path`. The result
        always exposes ``local_path`` as a readable file on disk.
        Callers must ``cleanup()`` when done; :class:`StagedAsset` also
        works as a context manager.
        """


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

    def stage_local(self, key_or_path: str) -> StagedAsset:
        # Accept any one of:
        #   1. an absolute path returned by a previous ``save()``
        #   2. a storage key relative to ``self.root``
        #   3. an arbitrary existing local path (e.g. an upstream artifact
        #      that was never routed through this storage instance)
        candidate = Path(key_or_path)
        if candidate.is_absolute() and candidate.exists():
            return StagedAsset(local_path=str(candidate))
        relative = self.root / key_or_path
        if relative.exists():
            return StagedAsset(local_path=str(relative))
        if candidate.exists():
            return StagedAsset(local_path=str(candidate.resolve()))
        raise FileNotFoundError(
            f"LocalStorage.stage_local: asset not found: {key_or_path}"
        )


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

    def stage_local(self, key_or_path: str) -> StagedAsset:
        key = self._resolve_key(key_or_path)
        tmpdir = tempfile.mkdtemp(prefix="shorts_staged_")
        # Preserve the original file extension so ffmpeg can pick the
        # right demuxer by name.
        suffix = Path(key).suffix or ""
        local_path = Path(tmpdir) / f"asset{suffix}"
        self.client.download_file(self.bucket, key, str(local_path))
        return StagedAsset(local_path=str(local_path), _cleanup_dir=tmpdir)

    def _resolve_key(self, key_or_path: str) -> str:
        prefix = f"s3://{self.bucket}/"
        if key_or_path.startswith(prefix):
            return key_or_path[len(prefix):]
        if key_or_path.startswith("s3://"):
            raise ValueError(
                f"S3Storage.stage_local: path targets a different bucket: {key_or_path}"
            )
        return key_or_path


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

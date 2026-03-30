"""
Raw document storage.
Saves incoming documents to organized local filesystem.
Production: swap for S3/MinIO with same interface.
"""

import os
import hashlib
from datetime import datetime
from pathlib import Path

import aiofiles


class DocumentStorage:
    """Save raw documents to local storage with organized directory structure."""

    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def save(
        self,
        raw_bytes: bytes,
        filename: str,
        source_channel: str,
    ) -> str:
        """
        Save raw document bytes to storage.

        Directory structure: base_path/YYYY/MM/channel/hash_filename
        Returns the relative storage path.
        """
        now = datetime.utcnow()
        doc_hash = self.compute_hash(raw_bytes)

        # Organize: year/month/channel/
        dir_path = self.base_path / str(now.year) / f"{now.month:02d}" / source_channel
        dir_path.mkdir(parents=True, exist_ok=True)

        # Filename: hash prefix + original name (avoids collisions)
        safe_filename = self._sanitize_filename(filename)
        stored_name = f"{doc_hash[:12]}_{safe_filename}"
        file_path = dir_path / stored_name

        # Write file
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(raw_bytes)

        # Return relative path from base
        return str(file_path.relative_to(self.base_path))

    @staticmethod
    def compute_hash(raw_bytes: bytes) -> str:
        """SHA256 hash of raw document bytes for deduplication."""
        return hashlib.sha256(raw_bytes).hexdigest()

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Remove unsafe characters from filename."""
        # Keep only alphanumeric, dots, hyphens, underscores
        safe = "".join(
            c if c.isalnum() or c in ".-_" else "_"
            for c in filename
        )
        # Limit length
        if len(safe) > 100:
            name, ext = os.path.splitext(safe)
            safe = name[:96] + ext
        return safe or "document"

    async def save_raw(self, raw_bytes: bytes, relative_path: str) -> str:
        """Save raw bytes to a specific relative path (for sidecar files)."""
        file_path = self.base_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(raw_bytes)
        return relative_path

    async def read(self, relative_path: str) -> bytes:
        """Read a stored document by its relative path."""
        file_path = self.base_path / relative_path
        async with aiofiles.open(file_path, "rb") as f:
            return await f.read()

    def get_absolute_path(self, relative_path: str) -> Path:
        """Get absolute filesystem path for a stored document."""
        return self.base_path / relative_path

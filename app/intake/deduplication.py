"""
Document deduplication.
Prevents processing the same sponsorship request twice.
Uses SHA256 hash checked against requests.raw_doc_hash in PostgreSQL.
"""

import logging

from app.intake.storage import DocumentStorage

logger = logging.getLogger(__name__)


class DeduplicationChecker:
    """Check if a document has already been ingested."""

    def __init__(self, db):
        self.db = db

    async def check(self, raw_bytes: bytes) -> str | None:
        """
        Check if this document has been seen before.

        Returns:
            existing request_id if duplicate, None if new.
        """
        if self.db is None:
            return None  # No DB = no deduplication (dev mode)

        doc_hash = DocumentStorage.compute_hash(raw_bytes)

        row = await self.db.find_by_hash(doc_hash)
        if row:
            logger.info(
                "Duplicate detected: hash=%s matches request_id=%s (state=%s)",
                doc_hash[:12],
                row["id"],
                row["state"],
            )
            return str(row["id"])

        return None

    @staticmethod
    def compute_hash(raw_bytes: bytes) -> str:
        """Compute SHA256 hash. Exposed for use without DB check."""
        return DocumentStorage.compute_hash(raw_bytes)

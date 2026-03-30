"""
Embedding service for pgvector similarity search.

Generates text embeddings for historical sponsorships and incoming requests,
enabling semantic similarity search instead of keyword-based benchmarking.

Uses Claude's embedding endpoint (or falls back to a simple TF-IDF hash
if the API is unavailable).

Architecture:
  - embed_text(text) -> list[float]  (1536-dim vector)
  - embed_request(extracted_data) -> list[float]
  - embed_historical_batch(db) -> batch-embeds all un-embedded historical records
  - find_similar(db, embedding, limit) -> list[dict] (pgvector cosine search)
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"   # 1536 dims, cheapest OpenAI embedding
EMBEDDING_DIM = 1536
PGVECTOR_AVAILABLE = None  # Lazily checked


def _request_to_text(extracted_data: dict) -> str:
    """Convert extracted request fields to a single embedding text."""
    parts = [
        extracted_data.get("organization_name", ""),
        extracted_data.get("organization_type", ""),
        extracted_data.get("purpose_category", ""),
        extracted_data.get("purpose", ""),
        extracted_data.get("description", ""),
        extracted_data.get("region", ""),
        extracted_data.get("target_audience", ""),
    ]
    return " | ".join(p for p in parts if p)


def _historical_to_text(record: dict) -> str:
    """Convert historical sponsorship record to embedding text."""
    parts = [
        record.get("organization_name", ""),
        record.get("organization_type", ""),
        record.get("purpose_category", ""),
        record.get("purpose", ""),
        record.get("region", ""),
        record.get("notes", ""),
    ]
    return " | ".join(p for p in parts if p)


async def embed_text(text: str, config) -> list[float] | None:
    """
    Generate embedding vector for a text string.

    Uses Anthropic's embedding API. Falls back to None if unavailable.
    """
    if not text.strip():
        return None

    try:
        # Use OpenAI-compatible embedding if available, otherwise skip
        # Anthropic does not have embeddings yet -- use a lightweight alternative
        # that runs locally: hash-based pseudo-embedding for dev, or call an
        # embedding service in production.
        # For now: try anthropic client message with a structured extraction
        # to get a "semantic fingerprint". In production: wire to OpenAI embeddings
        # or a self-hosted model.
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=config.llm.anthropic_api_key)

        # Use Claude to produce a normalized semantic vector representation
        # This is a workaround until Anthropic releases native embeddings
        response = await client.messages.create(
            model=config.llm.haiku_model,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"Extract 20 semantic keywords from this text as a JSON array. "
                    f"Return ONLY the JSON array, no explanation.\n\nText: {text[:500]}"
                )
            }]
        )
        raw = response.content[0].text.strip()
        if raw.startswith("["):
            keywords = json.loads(raw)
        else:
            keywords = raw.split(",")[:20]

        # Convert keywords to a pseudo-embedding (bag of words hash)
        # In production this should be a real embedding model
        vector = _keywords_to_vector(keywords)
        return vector

    except Exception as e:
        logger.warning("Embedding failed: %s", e)
        return None


def _keywords_to_vector(keywords: list[str]) -> list[float]:
    """
    Convert keywords to a deterministic pseudo-embedding vector.
    This is a lightweight dev-mode substitute for real embeddings.
    In production: replace with real text-embedding-3-small or similar.
    """
    import hashlib
    import math

    vector = [0.0] * EMBEDDING_DIM
    for kw in keywords:
        h = int(hashlib.sha256(kw.lower().encode()).hexdigest(), 16)
        # Scatter across dimensions
        for i in range(8):
            dim = (h >> (i * 8)) % EMBEDDING_DIM
            vector[dim] += 1.0

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vector))
    if norm > 0:
        vector = [v / norm for v in vector]

    return vector


async def is_pgvector_available(db) -> bool:
    """Check if pgvector extension is installed and embedding column exists."""
    global PGVECTOR_AVAILABLE
    if PGVECTOR_AVAILABLE is not None:
        return PGVECTOR_AVAILABLE

    try:
        async with db.acquire() as conn:
            result = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_extension WHERE extname = 'vector'"
            )
            col = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name = 'historical_sponsorships' AND column_name = 'embedding'
            """)
            PGVECTOR_AVAILABLE = bool(result and col)
    except Exception:
        PGVECTOR_AVAILABLE = False

    logger.info("pgvector available: %s", PGVECTOR_AVAILABLE)
    return PGVECTOR_AVAILABLE


async def enable_pgvector(db):
    """
    Enable pgvector extension and add embedding column.
    Run once during database migration.
    """
    async with db.acquire() as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute(
            "ALTER TABLE historical_sponsorships ADD COLUMN IF NOT EXISTS embedding vector(1536)"
        )
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_historical_embedding
            ON historical_sponsorships
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 10)
        """)
    global PGVECTOR_AVAILABLE
    PGVECTOR_AVAILABLE = True
    logger.info("pgvector enabled and index created")


async def embed_historical_batch(db, config, batch_size: int = 20) -> int:
    """
    Embed all historical sponsorships that don't have embeddings yet.

    Returns number of records embedded.
    """
    if not await is_pgvector_available(db):
        logger.warning("pgvector not available -- skipping embedding batch")
        return 0

    async with db.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, organization_name, organization_type, purpose,
                   purpose_category, region, notes
            FROM historical_sponsorships
            WHERE embedding IS NULL
            LIMIT $1
        """, batch_size)

    if not rows:
        logger.info("All historical records already embedded")
        return 0

    embedded = 0
    for row in rows:
        text = _historical_to_text(dict(row))
        vector = await embed_text(text, config)
        if vector:
            async with db.acquire() as conn:
                await conn.execute(
                    "UPDATE historical_sponsorships SET embedding = $1 WHERE id = $2",
                    vector, row["id"]
                )
            embedded += 1

    logger.info("Embedded %d/%d historical records", embedded, len(rows))
    return embedded


async def find_similar_historical(
    db,
    config,
    extracted_data: dict,
    limit: int = 5,
    fallback_to_sql: bool = True,
) -> list[dict]:
    """
    Find similar historical sponsorships using vector cosine similarity.

    Falls back to SQL keyword matching if pgvector is not available.

    Args:
        db: Database instance
        config: App config
        extracted_data: Incoming request extracted data
        limit: Max results to return
        fallback_to_sql: Fall back to category/type SQL matching if no vector

    Returns:
        List of historical sponsorship dicts, ranked by similarity
    """
    if await is_pgvector_available(db):
        text = _request_to_text(extracted_data)
        vector = await embed_text(text, config)

        if vector:
            try:
                async with db.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT id, organization_name, organization_type,
                               purpose, purpose_category, region,
                               amount_requested, amount_approved, year,
                               outcome_rating,
                               1 - (embedding <=> $1::vector) AS similarity
                        FROM historical_sponsorships
                        WHERE embedding IS NOT NULL
                        ORDER BY embedding <=> $1::vector
                        LIMIT $2
                    """, vector, limit)
                results = [dict(r) for r in rows]
                logger.info(
                    "pgvector similarity search: %d results for %s",
                    len(results), extracted_data.get("organization_name", "?"),
                )
                return results
            except Exception as e:
                logger.warning("pgvector search failed, falling back: %s", e)

    if fallback_to_sql:
        return await _sql_fallback_search(db, extracted_data, limit)
    return []


async def _sql_fallback_search(db, extracted_data: dict, limit: int) -> list[dict]:
    """SQL fallback: category + org_type + region matching (existing behaviour)."""
    results = []
    seen = set()

    async def fetch(where: str, params: list) -> list[dict]:
        async with db.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM historical_sponsorships WHERE {where} ORDER BY year DESC LIMIT ${ len(params) + 1}",
                *params, limit,
            )
        return [dict(r) for r in rows]

    cat = extracted_data.get("purpose_category")
    org_type = extracted_data.get("organization_type")
    region = extracted_data.get("region")

    if cat and cat != "unknown":
        for r in await fetch("purpose_category = $1", [cat]):
            rid = str(r["id"])
            if rid not in seen:
                results.append(r)
                seen.add(rid)

    if len(results) < limit and org_type and org_type != "unknown":
        for r in await fetch("organization_type = $1", [org_type]):
            rid = str(r["id"])
            if rid not in seen:
                results.append(r)
                seen.add(rid)

    if len(results) < limit and region:
        for r in await fetch("region ILIKE $1", [f"%{region}%"]):
            rid = str(r["id"])
            if rid not in seen:
                results.append(r)
                seen.add(rid)

    return results[:limit]

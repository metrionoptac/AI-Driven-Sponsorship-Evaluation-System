"""
Phase 01 / Block A -- runtime tests for the ingest() core (T01.1 - T01.9).

Runs against the REAL Postgres from .env and the REAL UnifiedIngestionService.
The only substitution: _execute_pipeline is replaced by a spy so no LLM pipeline
runs (Block A ends at dispatch). Test rows are deleted afterwards.

Run:  python tests/phase01_block_a.py
"""

import asyncio
import os
import re
import shutil
import sys
import uuid as uuid_mod
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

from app.intake.service import UnifiedIngestionService
from app.intake.storage import DocumentStorage
from app.persistence.database import Database

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_DATA = os.path.join(ROOT, "test_data", "phase_01")
TEST_STORAGE = os.path.join(TEST_DATA, "storage_block_a")

RESULTS = []          # (test_id, passed, detail)
CREATED_IDS = []      # request ids to clean up


def record(test_id: str, passed: bool, detail: str):
    RESULTS.append((test_id, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {test_id}: {detail}")


def load_pdf_bytes(name: str, nonce: bytes) -> bytes:
    """Load a dummy PDF and append a nonce so every run has fresh, unique bytes
    (trailing bytes after %%EOF are legal in PDF)."""
    with open(os.path.join(TEST_DATA, name), "rb") as f:
        return f.read() + b"\n%nonce:" + nonce


def make_service(db, storage, dedup_enabled=True, with_pipeline=True):
    """Real service; pipeline_executor is a truthy sentinel and _execute_pipeline
    is replaced with a spy recorder."""
    config = SimpleNamespace(intake=SimpleNamespace(dedup_enabled=dedup_enabled))
    svc = UnifiedIngestionService(
        db=db,
        storage=storage,
        pipeline_executor=object() if with_pipeline else None,
        email_sender=None,
        config=config,
    )
    svc.pipeline_calls = []

    async def _spy(request_id, **kwargs):
        # kwargs absorbs dispatch options (e.g. skip_classification) so the
        # spy survives signature growth on the real _execute_pipeline
        svc.pipeline_calls.append(request_id)

    svc._execute_pipeline = _spy
    return svc


async def main():
    load_dotenv(os.path.join(ROOT, ".env"))
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("FATAL: DATABASE_URL not set")
        return 1

    db = Database(db_url, min_size=1, max_size=3)
    await db.connect()
    storage = DocumentStorage(TEST_STORAGE)
    run_nonce = uuid_mod.uuid4().hex.encode()

    try:
        # ---------------- T01.1 dedup detects identical document ----------------
        print("T01.1 dedup detects identical bytes")
        svc = make_service(db, storage)
        data = load_pdf_bytes("dummy_request.pdf", run_nonce + b"-t1")
        r1 = await svc.ingest(data, "dummy_request.pdf", "upload")
        CREATED_IDS.append(r1.request_id)
        r2 = await svc.ingest(data, "dummy_request.pdf", "upload")
        async with db.acquire() as conn:
            n_rows = await conn.fetchval(
                "SELECT COUNT(*) FROM requests WHERE id = ANY($1::uuid[])",
                [uuid_mod.UUID(r1.request_id)],
            )
        record(
            "T01.1",
            r2.is_duplicate is True and r2.request_id == r1.request_id and n_rows == 1,
            f"2nd call is_duplicate={r2.is_duplicate}, same id={r2.request_id == r1.request_id}",
        )

        # ---------------- T01.2 different bytes -> two rows ----------------
        print("T01.2 dedup miss for different bytes")
        data_b = load_pdf_bytes("dummy_request_2.pdf", run_nonce + b"-t2")
        r3 = await svc.ingest(data_b, "dummy_request_2.pdf", "upload")
        CREATED_IDS.append(r3.request_id)
        record(
            "T01.2",
            r3.is_duplicate is False and r3.request_id != r1.request_id,
            f"distinct ids: {r1.request_id[:8]} vs {r3.request_id[:8]}",
        )

        # ---------------- T01.3 dedup disabled ----------------
        print("T01.3 dedup disabled -> both processed, no UNIQUE violation")
        svc_off = make_service(db, storage, dedup_enabled=False)
        data_c = load_pdf_bytes("dummy_request.pdf", run_nonce + b"-t3")
        r4 = await svc_off.ingest(data_c, "dummy_request.pdf", "upload")
        r5 = await svc_off.ingest(data_c, "dummy_request.pdf", "upload")
        CREATED_IDS.extend([r4.request_id, r5.request_id])
        row4 = await db.get_request(r4.request_id)
        row5 = await db.get_request(r5.request_id)
        record(
            "T01.3",
            (not r4.is_duplicate and not r5.is_duplicate
             and r4.request_id != r5.request_id
             and row4["raw_doc_hash"] != row5["raw_doc_hash"]),
            f"two rows, hashes differ (suffix): {row4['raw_doc_hash'][-8:]} vs {row5['raw_doc_hash'][-8:]}",
        )

        # ---------------- T01.4 raw bytes stored exactly ----------------
        print("T01.4 raw bytes stored byte-identical")
        row1 = await db.get_request(r1.request_id)
        stored = await storage.read(row1["raw_doc_path"])
        record("T01.4", stored == data, f"{len(stored)} bytes match input exactly: {stored == data}")

        # ---------------- T01.5 request row fields ----------------
        print("T01.5 request row created correctly")
        display_ok = bool(re.fullmatch(r"SP-\d{4}-\d{4,}", row1.get("display_id") or ""))
        checks = {
            "state=received": row1["state"] == "received",
            "display_id": display_ok,
            "hash set": bool(row1["raw_doc_hash"]),
            "received_via=upload": row1["received_via"] == "upload",
            "format=pdf": row1["source_format"] == "pdf",
        }
        record("T01.5", all(checks.values()),
               ", ".join(f"{k}={'OK' if v else 'BAD'}" for k, v in checks.items())
               + f" (display_id={row1.get('display_id')})")

        # ---------------- T01.6 pipeline_mode honored ----------------
        print("T01.6 metadata.pipeline_mode='autopilot' stored")
        data_d = load_pdf_bytes("dummy_request_2.pdf", run_nonce + b"-t6")
        r6 = await svc.ingest(data_d, "dummy_request_2.pdf", "upload",
                              metadata={"pipeline_mode": "autopilot"})
        CREATED_IDS.append(r6.request_id)
        row6 = await db.get_request(r6.request_id)
        record("T01.6", row6["pipeline_mode"] == "autopilot",
               f"pipeline_mode={row6['pipeline_mode']}")

        # ---------------- T01.7 pipeline dispatched once per non-duplicate ----------------
        print("T01.7 pipeline dispatched exactly once per non-duplicate ingest")
        await asyncio.sleep(0.2)  # let fire-and-forget tasks run
        # svc saw: r1 (new), r2 (dup), r3 (new), r6 (new) -> 3 dispatches
        expected = sorted([r1.request_id, r3.request_id, r6.request_id])
        got = sorted(svc.pipeline_calls)
        record("T01.7", got == expected,
               f"dispatched {len(svc.pipeline_calls)}x, duplicates not dispatched: "
               f"{r2.request_id not in svc.pipeline_calls or r1.request_id in svc.pipeline_calls}")

        # ---------------- T01.8 DB-less fallback ----------------
        print("T01.8 db=None fallback")
        svc_nodb = make_service(None, storage, with_pipeline=False)
        data_e = load_pdf_bytes("dummy_request.pdf", run_nonce + b"-t8")
        r8 = await svc_nodb.ingest(data_e, "dummy_request.pdf", "upload")
        valid_uuid = True
        try:
            uuid_mod.UUID(r8.request_id)
        except ValueError:
            valid_uuid = False
        record("T01.8", valid_uuid and not r8.is_duplicate,
               f"in-memory request_id={r8.request_id[:8]}..., no crash")

        # ---------------- T01.9 empty input (B19 fix: must be rejected) ----------------
        print("T01.9 empty bytes b'' rejected with ValueError")
        try:
            r9 = await svc.ingest(b"", "empty.txt", "upload")
            if not r9.is_duplicate:
                CREATED_IDS.append(r9.request_id)
            record("T01.9", False,
                   f"B19 REGRESSION: empty input accepted, request {r9.request_id[:8]} created")
        except ValueError as e:
            record("T01.9", True, f"rejected with ValueError: {e}")
        except Exception as e:
            record("T01.9", False, f"wrong exception type: {type(e).__name__}: {e}")

    finally:
        # ---------------- cleanup: remove test rows + storage ----------------
        print("\nCleanup...")
        try:
            ids = [uuid_mod.UUID(i) for i in CREATED_IDS]
            async with db.acquire() as conn:
                await conn.execute("DELETE FROM audit_log WHERE request_id = ANY($1::uuid[])", ids)
                deleted = await conn.execute("DELETE FROM requests WHERE id = ANY($1::uuid[])", ids)
            print(f"  removed test rows: {deleted}")
        except Exception as e:
            print(f"  WARNING cleanup failed: {e} -- delete rows manually: {CREATED_IDS}")
        shutil.rmtree(TEST_STORAGE, ignore_errors=True)
        await db.disconnect()

    # ---------------- summary ----------------
    print("\n===== BLOCK A SUMMARY =====")
    failed = 0
    for test_id, passed, detail in RESULTS:
        print(f"  {test_id}: {'PASS' if passed else 'FAIL'}")
        if not passed:
            failed += 1
    print(f"===== {len(RESULTS) - failed}/{len(RESULTS)} passed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""
Reset script: Deletes all test sponsorship requests so you can resend the same email.
Usage: python reset_requests.py
"""
import asyncio
import asyncpg

DB_URL = "postgresql://sponsorship:sponsorship@localhost:5432/sponsorship_db"

async def main():
    conn = await asyncpg.connect(DB_URL)

    # Show current requests
    rows = await conn.fetch(
        "SELECT id, source_email, state, created_at FROM requests ORDER BY created_at DESC LIMIT 20"
    )
    if not rows:
        print("No requests found. Already clean!")
        await conn.close()
        return

    print(f"\nFound {len(rows)} request(s):\n")
    print(f"{'ID':<40} {'Source':<45} {'State':<15}")
    print("-" * 100)

    # Separate historical (126 pre-loaded) from test requests
    test_ids = []
    for r in rows:
        email = r["source_email"] or "-"
        is_test = ("kartik" in email.lower() or "google" in email.lower() or "no-reply" in email.lower())
        marker = " << TEST" if is_test else ""
        print(f"{str(r['id']):<40} {email:<45} {r['state']:<15}{marker}")
        if is_test:
            test_ids.append(r["id"])

    if not test_ids:
        print("\nNo test requests to delete.")
        await conn.close()
        return

    print(f"\nDeleting {len(test_ids)} test request(s)...")

    # Delete from all related tables (respecting foreign keys)
    for table in [
        "audit_log", "completions", "decisions", "recommendations",
        "evaluation_results", "eligibility_results", "extraction_results",
        "verification_results", "follow_ups", "email_drafts",
        "defer_events", "sla_events", "gate2_results", "override_events",
    ]:
        try:
            result = await conn.execute(
                f"DELETE FROM {table} WHERE request_id = ANY($1::uuid[])", test_ids
            )
            count = int(result.split()[-1])
            if count > 0:
                print(f"  {table}: deleted {count}")
        except Exception:
            pass

    # Delete the requests themselves
    result = await conn.execute("DELETE FROM requests WHERE id = ANY($1::uuid[])", test_ids)
    count = int(result.split()[-1])
    print(f"  requests: deleted {count}")

    remaining = await conn.fetchval("SELECT count(*) FROM requests")
    print(f"\nDone! Remaining requests: {remaining}")
    print("You can now resend the same email.")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())

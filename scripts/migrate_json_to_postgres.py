#!/usr/bin/env python3
"""Migrate history data from JSON to PostgreSQL."""
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from webapi.config.database import SessionLocal, engine
from webapi.config.database import Base
from webapi.models.database import AnalysisTask

HISTORY_JSON_PATH = Path(__file__).parent.parent / "web" / "data" / "history.json"


def parse_datetime(value):
    """Parse an ISO-format datetime string, returning None for missing/invalid values."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def ensure_table():
    """Verify the analysis_tasks table exists (Alembic should create it)."""
    from sqlalchemy import inspect
    inspector = inspect(engine)
    if not inspector.has_table("analysis_tasks"):
        raise RuntimeError(
            "analysis_tasks table does not exist. "
            "Run 'alembic upgrade head' first to create the schema."
        )


def migrate(dry_run=False):
    """Read history.json and insert records into PostgreSQL.

    Args:
        dry_run: If True, only print what would be migrated without writing.
    """
    # --- 1. Read JSON ---
    if not HISTORY_JSON_PATH.exists():
        print(f"History file not found: {HISTORY_JSON_PATH}")
        sys.exit(1)

    with open(HISTORY_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", []) if isinstance(data, dict) else data

    if not records:
        print("No records found in history.json.")
        return

    print(f"Found {len(records)} record(s) in {HISTORY_JSON_PATH}")

    if dry_run:
        print("\n--- DRY RUN (no data will be written) ---\n")
        for i, rec in enumerate(records, 1):
            task_id = rec.get("task_id", "<missing>")
            symbol = rec.get("symbol", "<missing>")
            status = rec.get("status", "<missing>")
            print(f"  [{i:>3}] {task_id}  symbol={symbol}  status={status}")
        print(f"\nTotal: {len(records)} record(s) (dry run, nothing written)")
        return

    # --- 2. Ensure table exists ---
    ensure_table()

    # --- 3. Migrate to PostgreSQL ---
    db = SessionLocal()
    success = 0
    skipped = 0
    errors = 0

    try:
        total = len(records)
        for i, record in enumerate(records, 1):
            task_id = record.get("task_id")
            if not task_id:
                print(f"  [{i}/{total}] SKIP - no task_id, record ignored")
                skipped += 1
                continue

            # Check for existing record (skip duplicates)
            existing = db.query(AnalysisTask).get(task_id)
            if existing:
                skipped += 1
                if skipped <= 5 or skipped == total:
                    print(f"  [{i}/{total}] SKIP (already exists) {task_id}")
                continue

            # Build ORM object from JSON record
            raw_result = record.get("raw_result")
            raw_error = None
            if isinstance(raw_result, dict):
                raw_error = raw_result.get("error")

            task = AnalysisTask(
                task_id=task_id,
                symbol=record.get("symbol", ""),
                status=record.get("status", "COMPLETED"),
                created_at=parse_datetime(record.get("created_at")),
                updated_at=parse_datetime(record.get("updated_at")),
                completed_at=parse_datetime(record.get("updated_at"))
                if record.get("status") == "COMPLETED"
                else None,
                result=raw_result,
                decision=record.get("decision") or None,
                confidence=record.get("confidence"),
                message=None,
                error=raw_error,
            )
            db.add(task)
            success += 1

            # Progress every 10 records
            if i % 10 == 0 or i == total:
                print(f"  Progress: {i}/{total} (inserted={success}, skipped={skipped})")

        # Commit all at once
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"\nError during migration: {exc}")
        errors += 1
        raise
    finally:
        db.close()

    # --- 4. Summary ---
    print("\n--- Migration Summary ---")
    print(f"  Total records in JSON : {len(records)}")
    print(f"  Successfully migrated : {success}")
    print(f"  Skipped (duplicates)  : {skipped}")
    print(f"  Errors                : {errors}")
    print(f"  Source file           : {HISTORY_JSON_PATH}")
    print(f"  Database              : {engine.url}")


def main():
    """CLI entry point."""
    dry_run = "--dry-run" in sys.argv

    print("=== JSON -> PostgreSQL Migration ===\n")

    if dry_run:
        print("Running in DRY RUN mode (use without --dry-run to migrate)\n")

    migrate(dry_run=dry_run)


if __name__ == "__main__":
    main()

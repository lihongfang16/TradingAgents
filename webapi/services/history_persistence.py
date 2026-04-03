"""Local history persistence for API service.

This module provides history persistence without API dependencies,
suitable for use from the API service layer.
"""
import json
import os
from datetime import datetime
from typing import Dict, Any, List

# History file path (same as web component)
HISTORY_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'web', 'data')
HISTORY_FILE = os.path.join(HISTORY_DIR, 'history.json')


def _ensure_history_dir():
    """Ensure history directory exists."""
    os.makedirs(HISTORY_DIR, exist_ok=True)


def _load_local_history() -> List[Dict[str, Any]]:
    """Load only local history records (no API calls)."""
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("records", [])
    except Exception:
        pass
    return []


def _save_local_history(records: List[Dict[str, Any]]):
    """Save history records to local file."""
    _ensure_history_dir()
    data = {
        "version": "1.0",
        "records": records
    }
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def add_to_local_history(
    task_id: str,
    symbol: str,
    result: Dict[str, Any],
    created_at: str = None,
    updated_at: str = None
):
    """Add or update a history record in local storage.

    This function only accesses local files and does not make API calls.
    It is safe to call from the API service layer.

    Args:
        task_id: The task ID
        symbol: Stock symbol
        result: Analysis result dictionary
        created_at: Task creation timestamp (ISO format)
        updated_at: Task update timestamp (ISO format)
    """
    try:
        records = _load_local_history()

        # Check if record already exists
        existing_idx = None
        for i, r in enumerate(records):
            if r.get("task_id") == task_id:
                existing_idx = i
                break

        # Use provided timestamps or current time
        now = datetime.now().isoformat()
        created = created_at or now
        updated = updated_at or now

        # Build record with raw_result for full analysis data
        # Keep summary fields at top level for quick access
        record = {
            "task_id": task_id,
            "symbol": symbol,
            "created_at": created,
            "updated_at": updated,
            # Summary fields for quick display
            "status": result.get("status"),
            "decision": result.get("decision", "UNKNOWN"),
            # Full result data for detail view
            "raw_result": result
        }

        if existing_idx is not None:
            # Update existing record, preserving original created_at
            record["created_at"] = records[existing_idx].get("created_at", created)
            records[existing_idx] = record
        else:
            # Add new record
            records.append(record)

        # Save back to file
        _save_local_history(records)

    except Exception as e:
        # Log error but don't raise
        print(f"History persistence error: {e}")

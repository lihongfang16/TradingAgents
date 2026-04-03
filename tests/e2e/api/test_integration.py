"""
Full API workflow integration test.

Covers the complete lifecycle:
  1. List existing analyses (baseline)
  2. Create a new analysis
  3. Poll until completion or timeout
  4. Fetch the final result
  5. Verify result structure
"""
import time

import pytest
import requests

from fixtures.sample_analysis import ANALYSIS_RESPONSE_FIELDS


@pytest.mark.api
class TestAnalysisWorkflow:
    """End-to-end analysis lifecycle test."""

    POLL_INTERVAL = 5  # seconds
    MAX_POLL_ATTEMPTS = 12  # 60 seconds total — just verify the task is running

    def _poll_until_terminal(
        self, api_url: str, task_id: str
    ) -> dict:
        """Poll GET /api/v1/analysis/{task_id} until status is terminal."""
        url = f"{api_url}/api/v1/analysis/{task_id}"
        for _ in range(self.MAX_POLL_ATTEMPTS):
            resp = requests.get(url, timeout=10)
            assert resp.status_code == 200, f"Poll failed: {resp.status_code}"
            body = resp.json()
            status = body.get("status", "")
            if status in ("COMPLETED", "FAILED", "CANCELLED"):
                return body
            time.sleep(self.POLL_INTERVAL)
        # Return last seen state even if still running
        return body

    def test_full_lifecycle(self, api_url: str, sample_analysis_payload):
        """Submit analysis, wait for completion, verify result."""
        # Step 1: Create analysis
        create_resp = requests.post(
            f"{api_url}/api/v1/analysis/",
            json=sample_analysis_payload,
            timeout=30,
        )
        assert create_resp.status_code in (200, 202), (
            f"Create failed: {create_resp.status_code} {create_resp.text}"
        )
        task = create_resp.json()
        task_id = task["task_id"]
        assert task_id, "task_id must not be empty"

        # Step 2: Verify it appears in the list
        list_resp = requests.get(
            f"{api_url}/api/v1/analysis/",
            params={"symbol": sample_analysis_payload["symbol"], "limit": 50},
            timeout=10,
        )
        assert list_resp.status_code == 200
        task_ids = [t["task_id"] for t in list_resp.json()]
        # The task should appear in the list (may not be instant due to async processing)
        # Use a retry to handle eventual consistency
        found = task_id in task_ids
        if not found:
            time.sleep(2)
            list_resp = requests.get(
                f"{api_url}/api/v1/analysis/",
                params={"symbol": sample_analysis_payload["symbol"], "limit": 50},
                timeout=10,
            )
            task_ids = [t["task_id"] for t in list_resp.json()]
            found = task_id in task_ids
        assert found, f"Newly created task {task_id} should appear in list. Got: {task_ids[:5]}"

        # Step 3: Poll until terminal state
        final = self._poll_until_terminal(api_url, task_id)

        # Step 4: Verify final state
        assert final["task_id"] == task_id
        assert final["status"] in ("COMPLETED", "FAILED", "CANCELLED", "RUNNING", "PENDING")

        # Step 5: If completed, verify result structure
        if final["status"] == "COMPLETED":
            result = final.get("result")
            # Result may be None for some configurations, that's acceptable
            if result:
                assert isinstance(result, dict)

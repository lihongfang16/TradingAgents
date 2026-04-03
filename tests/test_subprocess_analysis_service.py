"""Unit tests for subprocess-based analysis execution."""

# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnusedCallResult=false, reportPrivateUsage=false, reportUnannotatedClassAttribute=false, reportUninitializedInstanceVariable=false, reportImplicitOverride=false, reportAny=false

import asyncio
import importlib
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from webapi.models.analysis import AnalysisRequest, AnalysisResponse, AnalysisStatus, StockExchange

analysis_service_module = importlib.import_module("webapi.services.analysis_service")
scheduler_service_module = importlib.import_module("webapi.services.scheduler_service")
subprocess_runner_module = importlib.import_module("webapi.subprocess_runner")


def _make_response(task_id: str, status: AnalysisStatus, symbol: str = "000001") -> AnalysisResponse:
    return AnalysisResponse(
        task_id=task_id,
        status=status,
        symbol=symbol,
        message=status.value,
        result={"signal": {"decision": "BUY"}} if status == AnalysisStatus.COMPLETED else None,
    )


class TestAnalysisServiceSubprocessMode(unittest.IsolatedAsyncioTestCase):
    """Verify the new blocking/non-blocking subprocess flow."""

    def setUp(self):
        analysis_service_module.AnalysisService._instance = None
        self.service = analysis_service_module.AnalysisService()
        self.request = AnalysisRequest(symbol="000001", exchange=StockExchange.CN)

    async def test_run_analysis_non_blocking_returns_pending(self):
        callback = Mock()
        state = {"done": False}

        async def fake_run_subprocess(task_id, request):
            self.assertEqual(task_id, "task-nb")
            self.assertEqual(request.symbol, "000001")
            state["done"] = True

        def fake_get_task(task_id):
            return _make_response(task_id, AnalysisStatus.COMPLETED) if state["done"] else None

        with patch.object(self.service, "get_task", side_effect=fake_get_task), patch.object(
            self.service,
            "create_task",
            side_effect=lambda request, task_id=None: _make_response(task_id or "generated", AnalysisStatus.PENDING, request.symbol),
        ), patch.object(self.service, "_update_task_status"), patch.object(
            self.service,
            "_run_subprocess",
            side_effect=fake_run_subprocess,
        ):
            response = await self.service.run_analysis(
                "task-nb",
                self.request,
                on_complete=callback,
                blocking=False,
            )
            self.assertEqual(response.status, AnalysisStatus.PENDING)
            self.assertEqual(response.task_id, "task-nb")

            await asyncio.gather(*list(self.service._background_tasks))

        callback.assert_called_once_with("task-nb", {"signal": {"decision": "BUY"}})

    async def test_run_analysis_blocking_waits_for_completion(self):
        state = {"done": False}

        async def fake_run_subprocess(task_id, request):
            state["done"] = True

        def fake_get_task(task_id):
            return _make_response(task_id, AnalysisStatus.COMPLETED) if state["done"] else None

        with patch.object(self.service, "get_task", side_effect=fake_get_task), patch.object(
            self.service,
            "create_task",
            side_effect=lambda request, task_id=None: _make_response(task_id or "generated", AnalysisStatus.PENDING, request.symbol),
        ), patch.object(self.service, "_update_task_status"), patch.object(
            self.service,
            "_run_subprocess",
            side_effect=fake_run_subprocess,
        ):
            response = await self.service.run_analysis("task-block", self.request, blocking=True)

        self.assertEqual(response.status, AnalysisStatus.COMPLETED)
        self.assertEqual(response.task_id, "task-block")

    async def test_background_subprocess_concurrency_is_limited_to_three(self):
        counts = {"current": 0, "max": 0}

        async def fake_run_subprocess(task_id, request):
            counts["current"] += 1
            counts["max"] = max(counts["max"], counts["current"])
            await asyncio.sleep(0.05)
            counts["current"] -= 1

        with patch.object(self.service, "get_task", return_value=None), patch.object(
            self.service,
            "create_task",
            side_effect=lambda request, task_id=None: _make_response(task_id or "generated", AnalysisStatus.PENDING, request.symbol),
        ), patch.object(self.service, "_update_task_status"), patch.object(
            self.service,
            "_run_subprocess",
            side_effect=fake_run_subprocess,
        ):
            responses = await asyncio.gather(
                *[
                    self.service.run_analysis(f"task-{idx}", self.request, blocking=False)
                    for idx in range(4)
                ]
            )
            await asyncio.gather(*list(self.service._background_tasks))

        self.assertTrue(all(response.status == AnalysisStatus.PENDING for response in responses))
        self.assertEqual(counts["max"], 3)


class TestSchedulerBlockingHelper(unittest.TestCase):
    """Verify scheduler uses blocking subprocess execution."""

    def test_run_blocking_analysis_passes_blocking_true(self):
        request = AnalysisRequest(symbol="000001", exchange=StockExchange.CN)
        expected = _make_response("task-scheduler", AnalysisStatus.COMPLETED)
        mock_service = MagicMock()
        mock_service.run_analysis = AsyncMock(return_value=expected)

        with patch("webapi.services.analysis_service.analysis_service", mock_service):
            result = scheduler_service_module._run_blocking_analysis("task-scheduler", request, timeout=1)

        self.assertEqual(result, expected)
        mock_service.run_analysis.assert_awaited_once()
        self.assertTrue(mock_service.run_analysis.await_args.kwargs["blocking"])


class TestSubprocessRunner(unittest.TestCase):
    """Verify subprocess entrypoint wiring."""

    def test_main_accepts_request_json_and_runs_analysis(self):
        payload = json.dumps(
            {
                "symbol": "000001",
                "exchange": "CN",
                "analysts": ["market"],
                "deep_model": "MiniMax-M2.7-highspeed",
            }
        )
        runner_instance = MagicMock()
        runner_instance.run.return_value = {"status": "success", "signal": {"decision": "BUY"}}

        with patch.object(subprocess_runner_module, "AnalysisRunner", return_value=runner_instance) as runner_cls, patch.object(
            subprocess_runner_module,
            "_update_task_status",
        ) as update_status, patch.object(
            subprocess_runner_module,
            "_update_task_result",
        ) as update_result, patch.object(
            subprocess_runner_module,
            "_update_queue_status",
        ) as update_queue:
            exit_code = subprocess_runner_module.main(["task-subprocess", payload])

        self.assertEqual(exit_code, 0)
        runner_cls.assert_called_once()
        self.assertEqual(runner_cls.call_args.kwargs["symbol"], "000001")
        self.assertEqual(runner_cls.call_args.kwargs["analysts"], ["market"])
        self.assertEqual(runner_cls.call_args.kwargs["llm_provider"], "openai")
        update_status.assert_called_once_with(
            "task-subprocess",
            AnalysisStatus.RUNNING.value,
            message="Analysis running for 000001",
        )
        update_result.assert_called_once_with(
            "task-subprocess",
            {"status": "success", "signal": {"decision": "BUY"}},
            AnalysisStatus.COMPLETED.value,
        )
        self.assertEqual(update_queue.call_count, 2)


if __name__ == "__main__":
    unittest.main()

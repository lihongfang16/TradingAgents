#!/usr/bin/env python3
"""Subprocess entrypoint for analysis execution."""

# Suppress noisy warnings that would pop up as Windows dialogs
import warnings
warnings.filterwarnings("ignore", message="urllib3.*doesn't match a supported version")
warnings.filterwarnings("ignore", category=RuntimeWarning, module="tradingagents")

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportGeneralTypeIssues=false, reportMissingTypeArgument=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAny=false, reportExplicitAny=false, reportUnusedCallResult=false, reportDeprecated=false

from dotenv import load_dotenv

# CRITICAL: load .env before importing modules that depend on it.
load_dotenv()

import platform

if platform.system() == "Windows":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import json
import logging
import os
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

from tradingagents.core.analysis_runner import AnalysisRunner
from webapi.config.database import SessionLocal
from webapi.models.analysis import AnalysisRequest, AnalysisStatus, StockExchange
from webapi.models.database import AnalysisTask
from webapi.services.queue_service import AnalysisQueueService

logger = logging.getLogger(__name__)
queue_service = AnalysisQueueService()


def _deserialize_request_data(request_data: Dict[str, Any]) -> AnalysisRequest:
    """Deserialize a dictionary payload into an AnalysisRequest."""
    exchange = request_data.get("exchange")
    if isinstance(exchange, str):
        request_data["exchange"] = StockExchange(exchange)
    return AnalysisRequest(**request_data)


def _deserialize_request(request_json: str) -> AnalysisRequest:
    """Deserialize a JSON payload into an AnalysisRequest."""
    return _deserialize_request_data(json.loads(request_json))


def _build_request_from_task(task_id: str) -> AnalysisRequest:
    """Fallback request reconstruction for legacy worker invocations."""
    db = SessionLocal()
    try:
        task = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id).first()
        if task is None:
            raise ValueError(f"Task {task_id} not found")

        return AnalysisRequest(
            symbol=task.symbol,
            date=task.created_at.strftime("%Y-%m-%d") if task.created_at else None,
            exchange=StockExchange.CN,
            analysts=["market", "news", "social", "fundamentals"],
        )
    finally:
        db.close()


def _load_request(task_id: str, request_json: Optional[str]) -> AnalysisRequest:
    """Load request payload from CLI JSON or fallback task metadata."""
    queued_payload = queue_service.get_request_payload(task_id)
    if isinstance(queued_payload, dict):
        return _deserialize_request_data(queued_payload)

    if request_json:
        try:
            return _deserialize_request(request_json)
        except json.JSONDecodeError:
            logger.warning("Request payload is not JSON, falling back to stored task metadata")

    return _build_request_from_task(task_id)


def _resolve_runner_config(request: AnalysisRequest) -> Dict[str, Optional[str]]:
    """Resolve provider/model/base_url/api_key for AnalysisRunner."""
    llm_provider = request.llm_provider or os.getenv("LLM_PROVIDER", "minimax")
    deep_model = request.deep_model or os.getenv("DEEP_THINK_LLM", "MiniMax-M2.7-highspeed")
    quick_model = request.quick_model or os.getenv("QUICK_THINK_LLM", deep_model)

    if llm_provider.lower() == "openai" and not request.llm_provider:
        model_lower = f"{deep_model} {quick_model}".lower()
        if "minimax" in model_lower:
            llm_provider = "minimax"

    base_url = None
    api_key = None
    if llm_provider.lower() == "minimax":
        base_url = os.getenv("MINIMAX_API_BASE") or os.getenv("MINIMAX_BASE_URL") or "https://api.minimax.chat/v1"
        api_key = os.getenv("MINIMAX_API_KEY") or os.getenv("OPENAI_API_KEY")
        llm_provider = "openai"

    return {
        "llm_provider": llm_provider,
        "llm_model": deep_model,
        "base_url": base_url,
        "api_key": api_key,
    }


def _extract_decision(signal: Any) -> Optional[str]:
    """Extract normalized decision text from the signal payload."""
    if isinstance(signal, dict):
        return signal.get("decision") or signal.get("signal")

    if isinstance(signal, str):
        valid = {"BUY", "OVERWEIGHT", "HOLD", "UNDERWEIGHT", "SELL"}
        for word in reversed(signal.strip().split()):
            normalized = word.upper().rstrip(".。")
            if normalized in valid:
                return normalized
        return signal.strip() or None

    return None


def _normalize_confidence(result: Dict[str, Any]) -> Optional[int]:
    """Convert confidence into an integer for the persisted column."""
    confidence = result.get("confidence")
    if confidence is None and isinstance(result.get("signal"), dict):
        confidence = result["signal"].get("confidence")
    if confidence is None:
        return None

    if isinstance(confidence, (int, float)):
        if 0 <= confidence <= 1:
            return int(round(confidence * 100))
        return int(round(confidence))

    return None


def _update_task_status(
    task_id: str,
    status: str,
    *,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Update task status in PostgreSQL."""
    db = SessionLocal()
    try:
        task = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id).first()
        if task is None:
            return

        now = datetime.utcnow()
        task.status = status
        task.updated_at = now
        if status in {
            AnalysisStatus.COMPLETED.value,
            AnalysisStatus.FAILED.value,
            AnalysisStatus.CANCELLED.value,
        }:
            task.completed_at = task.completed_at or now
        if message is not None:
            task.message = message
        if error is not None:
            task.error = error
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _update_task_result(task_id: str, result: Dict[str, Any], status: str) -> None:
    """Persist the final analysis result in PostgreSQL."""
    db = SessionLocal()
    try:
        task = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id).first()
        if task is None:
            return

        now = datetime.utcnow()
        task.status = status
        task.result = result
        task.updated_at = now
        task.completed_at = now
        task.message = "Analysis completed"
        task.error = None
        task.decision = _extract_decision(result.get("signal"))
        task.confidence = _normalize_confidence(result)

        llm_streams = result.get("llm_streams")
        if llm_streams:
            task.llm_streams = llm_streams

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _update_queue_status(
    task_id: str,
    status: str,
    *,
    worker_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Update persisted queue state when a queue row exists."""
    if status == "PROCESSING":
        queue_service.mark_processing(task_id, worker_id or "unknown")
    elif status == "COMPLETED":
        queue_service.mark_completed(task_id)
    elif status == "FAILED":
        queue_service.mark_failed(task_id, error or "Analysis failed")


def _update_progress(task_id: str, data: Dict[str, Any]) -> None:
    """Persist progress callbacks emitted by AnalysisRunner."""
    db = SessionLocal()
    try:
        task = db.query(AnalysisTask).filter(AnalysisTask.task_id == task_id).first()
        if task is None or task.status in {
            AnalysisStatus.COMPLETED.value,
            AnalysisStatus.FAILED.value,
            AnalysisStatus.CANCELLED.value,
        }:
            return

        task.updated_at = datetime.utcnow()
        task.progress_pct = data.get("progress_pct", data.get("progress", 0)) or 0
        task.current_agent = data.get("current_agent", "")

        agents_progress = data.get("agents_progress")
        if agents_progress is not None:
            task.agents_progress = agents_progress

        llm_streams = data.get("llm_streams")
        if llm_streams:
            existing_streams = task.llm_streams or {}
            existing_streams.update(llm_streams)
            task.llm_streams = existing_streams

        log_message = data.get("log") or data.get("message")
        if log_message:
            logs = list(task.logs or [])
            logs.append(
                {
                    "time": datetime.utcnow().isoformat(),
                    "agent": data.get("current_agent", "system"),
                    "message": log_message,
                }
            )
            task.logs = logs[-100:]

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint used by AnalysisService subprocess launches."""
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(
            "Usage: python -m webapi.subprocess_runner <task_id> [worker_id] [request_json]",
            file=sys.stderr,
        )
        return 1

    task_id = args[0]
    worker_id: Optional[str] = None
    request_json: Optional[str] = None

    if len(args) > 1:
        if args[1].lstrip().startswith("{"):
            request_json = args[1]
        else:
            worker_id = args[1]
            if len(args) > 2:
                request_json = args[2]

    try:
        request = _load_request(task_id, request_json)
        runner_config = _resolve_runner_config(request)

        _update_queue_status(task_id, "PROCESSING", worker_id=worker_id)
        _update_task_status(
            task_id,
            AnalysisStatus.RUNNING.value,
            message=f"Analysis running for {request.symbol}",
        )

        runner = AnalysisRunner(
            symbol=request.symbol,
            date=request.date or datetime.utcnow().strftime("%Y-%m-%d"),
            analysts=request.analysts or ["market", "news", "social", "fundamentals"],
            llm_model=runner_config["llm_model"],
            llm_provider=runner_config["llm_provider"],
            base_url=runner_config["base_url"],
            api_key=runner_config["api_key"],
            progress_callback=lambda data: _update_progress(task_id, data),
            max_iterations=300,
            fast_mode=request.is_quick,
        )
        result = runner.run()
        result["analysis_type"] = "quick" if request.is_quick else result.get("analysis_type", "full")

        if result.get("status") == "error":
            raise RuntimeError(result.get("error") or "AnalysisRunner returned error status")

        _update_task_result(task_id, result, AnalysisStatus.COMPLETED.value)
        _update_queue_status(task_id, "COMPLETED")
        return 0
    except Exception as exc:
        error_message = f"{exc}\n{traceback.format_exc()}"
        _update_queue_status(task_id, "FAILED", error=error_message)
        _update_task_status(
            task_id,
            AnalysisStatus.FAILED.value,
            message=f"Analysis failed for {task_id}",
            error=error_message,
        )
        print(error_message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

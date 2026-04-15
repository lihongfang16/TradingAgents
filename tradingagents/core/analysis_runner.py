# TradingAgents/core/analysis_runner.py
"""
Non-interactive, fully configurable runner for TradingAgents analysis workflow.
Can be called from both Streamlit UI and FastAPI.
"""

# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportExplicitAny=false, reportGeneralTypeIssues=false, reportAny=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnannotatedClassAttribute=false, reportDeprecated=false, reportMissingTypeArgument=false, reportUnusedImport=false, reportUnusedVariable=false

from datetime import datetime
import json
import re
from typing import Any, Callable, Dict, List, Optional

from tradingagents.dataflows.ashare_provider import AshareProvider
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


# Agent steps for progress tracking
AGENT_STEPS = [
    ("graph_setup", "🚀", "初始化分析图"),
    ("market_analyst", "📊", "市场分析师"),
    ("sentiment_analyst", "💭", "情绪分析师"),
    ("news_analyst", "📰", "新闻分析师"),
    ("fundamentals_analyst", "🏢", "基本面分析师"),
    ("persona_agents", "🎭", "投资者人设分析"),
    ("research_manager", "🔍", "研究经理"),
    ("bull_researcher", "🐂", "看涨研究员"),
    ("bear_researcher", "🐻", "看跌研究员"),
    ("trader", "💼", "交易员"),
    ("risk_manager", "⚠️", "风控经理"),
    ("portfolio_manager", "👔", "投资组合经理"),
]


class AnalysisRunner:
    """
    Non-interactive runner for TradingAgents analysis workflow.
    
    Provides a clean interface for running trading agent analysis
    without interactive prompts, suitable for Streamlit UI and FastAPI.
    """

    NODE_TO_STEP = {
        "Market Index Analyst": "market_index_analyst",
        "Market Analyst": "market_analyst",
        "Social Analyst": "sentiment_analyst",
        "News Analyst": "news_analyst",
        "Fundamentals Analyst": "fundamentals_analyst",
        "Warren Buffett": "persona_agents",
        "Michael Burry": "persona_agents",
        "Nassim Taleb": "persona_agents",
        "Stanley Druckenmiller": "persona_agents",
        "Cathie Wood": "persona_agents",
        "Charlie Munger": "persona_agents",
        "Persona Aggregator": "persona_agents",
        "Research Manager": "research_manager",
        "Quick Risk Check": "risk_manager",
        "Bull Researcher": "bull_researcher",
        "Bear Researcher": "bear_researcher",
        "Trader": "trader",
        "Portfolio Manager": "portfolio_manager",
    }
    RISK_NODES = {"Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"}
    IGNORE_NODES = {
        "tools_market_index",
        "tools_market",
        "tools_social",
        "tools_news",
        "tools_fundamentals",
        "Msg Clear Market Index",
        "Msg Clear Market",
        "Msg Clear Social",
        "Msg Clear News",
        "Msg Clear Fundamentals",
    }
    PERSONA_NODES = {
        "Warren Buffett", "Michael Burry", "Nassim Taleb",
        "Stanley Druckenmiller", "Cathie Wood", "Charlie Munger",
    }
    REPORT_MAX_CHARS = 2000
    SERIALIZE_MAX_DEPTH = 5
    SERIALIZE_STRING_MAX_CHARS = 5000
    RESEARCH_STEPS = {"bull_researcher", "bear_researcher"}
    INDETERMINATE_STEPS = {
        "bull_researcher",
        "bear_researcher",
        "research_manager",
        "risk_manager",
    }

    # Map LangGraph node names to AgentState report fields
    NODE_TO_REPORT_FIELD = {
        "Market Index Analyst": "market_index_report",
        "Market Analyst": "market_report",
        "Social Analyst": "sentiment_report",
        "News Analyst": "news_report",
        "Fundamentals Analyst": "fundamentals_report",
        "Persona Aggregator": "persona_report",
        "Research Manager": "investment_plan",
        "Trader": "trader_investment_plan",
        "Portfolio Manager": "final_trade_decision",
    }

    def __init__(
        self,
        symbol: str,
        date: str,
        analysts: List[str],
        llm_model: str,
        llm_provider: str,
        initial_cash: float = 100000.0,
        max_iterations: int = 300,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        fast_mode: bool = False,
    ):
        """
        Initialize the AnalysisRunner.

        Args:
            symbol: Stock symbol/ticker to analyze
            date: Trade date in format 'YYYY-MM-DD'
            analysts: List of analyst types to include (e.g., ["market", "news", "fundamentals"])
            llm_model: LLM model name for reasoning
            llm_provider: LLM provider (e.g., "openai", "anthropic", "google")
            initial_cash: Initial cash for portfolio (default: 100000.0)
            max_iterations: Maximum recursion/debate iterations (default: 300)
            base_url: Optional base URL for API endpoint
            api_key: Optional API key for LLM provider
            progress_callback: Optional callback function for progress updates
            fast_mode: If True, skip bull/bear debate nodes for faster analysis (default: False)
        """
        self.symbol = symbol
        self.date = date
        self.analysts = analysts
        self.llm_model = llm_model
        self.llm_provider = llm_provider
        self.initial_cash = initial_cash
        self.max_iterations = max_iterations
        self.base_url = base_url
        self.api_key = api_key
        self.progress_callback = progress_callback
        self.fast_mode = fast_mode
        
        # Build config from parameters
        self.config = self._build_config()
        
        # Graph instance (created lazily on run)
        self._graph: Optional[TradingAgentsGraph] = None
        
        # Progress tracking
        self._progress_pct = 0
        self._agents_progress: Dict[str, str] = {}
        self._current_agent = ""
        self._llm_streams: Dict[str, str] = {}
        self._analysis_started_at: Optional[datetime] = None

    def _build_config(self) -> Dict[str, Any]:
        """Build configuration dictionary from instance parameters."""
        config = DEFAULT_CONFIG.copy()
        config["llm_provider"] = self.llm_provider
        config["deep_think_llm"] = self.llm_model
        config["quick_think_llm"] = self.llm_model
        config["max_recur_limit"] = self.max_iterations
        if self.base_url:
            config["backend_url"] = self.base_url
        if self.api_key:
            config["api_key"] = self.api_key
        return config

    def _get_current_price(self) -> Optional[float]:
        """Fetch current stock price."""
        try:
            provider = AshareProvider()
            quote = provider.get_realtime_quote(self.symbol)
            if quote and quote.get('price'):
                return float(quote['price'])
        except Exception:
            pass
        return None

    def _report_progress(self, agents_progress: Dict[str, str], current_agent: str, progress_pct: int, message: str = ""):
        """Report progress via callback if provided."""
        if self.progress_callback:
            elapsed_time = self._get_elapsed_seconds()
            remaining_time = self._estimate_remaining_seconds(progress_pct, current_agent)
            self.progress_callback({
                "agents_progress": agents_progress.copy(),
                "current_agent": current_agent,
                "progress_pct": progress_pct,
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "llm_streams": self._llm_streams.copy(),
                "elapsed_time": elapsed_time,
                "remaining_time": remaining_time,
                "is_progress_indeterminate": remaining_time is None and 0 < progress_pct < 100,
            })

    def _get_elapsed_seconds(self) -> int:
        """Get elapsed analysis time in seconds."""
        if self._analysis_started_at is None:
            return 0
        return max(0, int((datetime.now() - self._analysis_started_at).total_seconds()))

    def _estimate_remaining_seconds(
        self,
        progress_pct: int,
        current_agent: str,
    ) -> Optional[int]:
        """Estimate remaining time when enough signal exists.

        Returns None for phases where linear estimation is too noisy.
        """
        if progress_pct >= 100:
            return 0

        if progress_pct <= 0:
            return None

        elapsed_seconds = self._get_elapsed_seconds()
        if elapsed_seconds <= 0:
            return None

        if progress_pct < 15 or current_agent in self.INDETERMINATE_STEPS:
            return None

        estimated_total = int(elapsed_seconds * 100 / max(progress_pct, 1))
        return max(0, estimated_total - elapsed_seconds)

    def _compute_step_progress(
        self,
        current_count: int,
        total_count: int,
        start_pct: int,
        end_pct: int,
    ) -> int:
        """Compute monotonic progress within a stage range."""
        if total_count <= 0:
            return end_pct
        span = end_pct - start_pct
        return start_pct + int((current_count / total_count) * span)

    def _run_graph_with_progress(
        self,
        *,
        initial_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run the graph with streamed node updates and mapped progress."""
        start_time = datetime.now()
        self._analysis_started_at = start_time
        self._progress_pct = 0
        self._llm_streams.clear()
        result = {
            "status": "success",
            "progress_pct": 0,
            "agents_progress": {},
            "current_agent": "initializing",
            "final_state": None,
            "signal": None,
            "error": None,
            "timestamp": start_time.isoformat(),
        }
        agents_progress = {step_id: "not_started" for step_id, _, _ in AGENT_STEPS}

        try:
            analyst_mapping = {
                "market_index": "market_index_analyst",
                "market": "market_analyst",
                "sentiment": "sentiment_analyst",
                "social": "sentiment_analyst",
                "news": "news_analyst",
                "fundamentals": "fundamentals_analyst",
            }
            configured_analyst_steps: List[str] = []
            for analyst in self.analysts:
                mapped = analyst_mapping.get(analyst)
                if mapped and mapped not in configured_analyst_steps:
                    configured_analyst_steps.append(mapped)

            completed_analysts = set()
            completed_research = set()
            completed_risk_nodes = set()
            completed_persona_nodes = set()
            active_steps = {"graph_setup", *configured_analyst_steps, "trader", "portfolio_manager"}
            if self.fast_mode:
                active_steps.add("risk_manager")
            else:
                active_steps.update({"research_manager", "bull_researcher", "bear_researcher", "risk_manager", "persona_agents"})

            def emit_progress(current_agent: str, progress_pct: int, message: str) -> None:
                normalized_progress = max(self._progress_pct, min(progress_pct, 100))
                self._progress_pct = normalized_progress
                result["current_agent"] = current_agent
                result["progress_pct"] = normalized_progress
                result["agents_progress"] = agents_progress.copy()
                self._report_progress(agents_progress, current_agent, normalized_progress, message)

            agents_progress["graph_setup"] = "in_progress"
            emit_progress("graph_setup", 5, "初始化分析图")

            graph_obj = self.graph
            run_state = initial_state or graph_obj.propagator.create_initial_state(self.symbol, self.date)

            agents_progress["graph_setup"] = "completed"
            emit_progress("graph_setup", 10, "分析图初始化完成")

            def on_graph_progress(update: Dict[str, Any]) -> None:
                node = update.get("node")
                if not node or node in self.IGNORE_NODES:
                    return

                state_update = update.get("state", {})
                if not state_update:
                    state_update = update

                report_field = self.NODE_TO_REPORT_FIELD.get(node)
                capture_step_id = self.NODE_TO_STEP.get(node, node)
                if report_field and report_field in state_update:
                    self._llm_streams[capture_step_id] = state_update[report_field]

                if node == "Research Manager":
                    if agents_progress["research_manager"] != "completed":
                        agents_progress["research_manager"] = "completed"
                        emit_progress("research_manager", 78, "研究经理已生成投资计划")
                    return

                step_id = self.NODE_TO_STEP.get(node)
                if step_id:
                    if step_id in configured_analyst_steps:
                        if agents_progress.get(step_id) == "not_started":
                            agents_progress[step_id] = "in_progress"

                        if step_id not in completed_analysts:
                            completed_analysts.add(step_id)
                            agents_progress[step_id] = "completed"
                            progress = self._compute_step_progress(
                                len(completed_analysts),
                                max(1, len(configured_analyst_steps)),
                                10,
                                55,
                            )
                            emit_progress(step_id, min(progress, 55), f"{step_id} 完成")
                        return

                    if step_id in self.RESEARCH_STEPS:
                        if agents_progress.get(step_id) == "not_started":
                            agents_progress[step_id] = "in_progress"

                        if step_id not in completed_research:
                            completed_research.add(step_id)
                            agents_progress[step_id] = "completed"
                            progress = self._compute_step_progress(
                                len(completed_research),
                                len(self.RESEARCH_STEPS),
                                60,
                                74,
                            )
                            emit_progress(step_id, min(progress, 74), f"{step_id} 完成")
                        return

                    if step_id == "trader":
                        if agents_progress["trader"] != "completed":
                            agents_progress["trader"] = "completed"
                            emit_progress("trader", 80, "交易员阶段完成")
                        return

                    if step_id == "risk_manager":
                        if agents_progress["risk_manager"] != "completed":
                            agents_progress["risk_manager"] = "completed"
                            emit_progress("risk_manager", 74, "快速风险检查完成")
                        return

                    if step_id == "portfolio_manager":
                        if agents_progress["portfolio_manager"] != "completed":
                            agents_progress["portfolio_manager"] = "completed"
                            emit_progress("portfolio_manager", 99, "投资组合经理已完成最终决策")
                        return

                if node in self.RISK_NODES:
                    if agents_progress["risk_manager"] == "not_started":
                        agents_progress["risk_manager"] = "in_progress"

                    if node not in completed_risk_nodes:
                        completed_risk_nodes.add(node)
                        progress = self._compute_step_progress(
                            len(completed_risk_nodes),
                            len(self.RISK_NODES),
                            85,
                            94,
                        )
                        if len(completed_risk_nodes) == len(self.RISK_NODES):
                            agents_progress["risk_manager"] = "completed"
                        emit_progress("risk_manager", min(progress, 94), f"风险辩论节点完成: {node}")

                # Persona agent progress tracking
                if node in self.PERSONA_NODES or node == "Persona Aggregator":
                    if node not in completed_persona_nodes:
                        completed_persona_nodes.add(node)
                        total_persona = len(self.PERSONA_NODES) + 1  # 6 agents + 1 aggregator
                        if agents_progress.get("persona_agents") == "not_started":
                            agents_progress["persona_agents"] = "in_progress"
                        progress = self._compute_step_progress(
                            len(completed_persona_nodes),
                            total_persona,
                            55,
                            60,
                        )
                        if len(completed_persona_nodes) == total_persona:
                            agents_progress["persona_agents"] = "completed"
                        emit_progress("persona_agents", min(progress, 60), f"Persona 节点完成: {node}")

            final_state, signal = graph_obj.propagate(
                self.symbol,
                self.date,
                progress_callback=on_graph_progress,
                initial_state=run_state,
            )

            for step_id in active_steps:
                if agents_progress.get(step_id) not in {"completed", "failed"}:
                    agents_progress[step_id] = "completed"

            self._extract_llm_streams_from_state(final_state)
            result["final_state"] = self._build_slim_final_state(final_state)
            result["signal"] = signal
            result.update(self._extract_structured_metrics(final_state, signal))
            price = self._get_current_price()
            result["price"] = price if price is not None else None
            result["progress_pct"] = 100
            result["current_agent"] = "completed"
            result["agents_progress"] = agents_progress.copy()
            result["status"] = "success"
            result["llm_streams"] = self._llm_streams.copy()
            self._progress_pct = 100
            self._report_progress(agents_progress, "completed", 100, "分析完成")

        except Exception as e:
            failing_step = result.get("current_agent", "")
            if isinstance(failing_step, str) and failing_step and failing_step in agents_progress and failing_step != "error":
                agents_progress[failing_step] = "failed"

            # Structured error classification
            error_type = self._classify_error(e)
            structured_error = {
                "type": error_type,
                "message": str(e),
                "agent": failing_step if failing_step else "unknown",
                "timestamp": datetime.now().isoformat(),
                "retry_count": result.get("retry_count", 0),
                "llm_params": {
                    "model": getattr(self, "current_model", None),
                    "timeout": self.config.get("llm_nodata_timeout_seconds", 120),
                }
            }

            result["status"] = "error"
            result["error"] = structured_error
            result["current_agent"] = "error"
            result["agents_progress"] = agents_progress.copy()
            result["llm_streams"] = self._llm_streams.copy()
            progress_pct = result.get("progress_pct", 0)
            progress_pct = progress_pct if isinstance(progress_pct, int) else 0
            self._report_progress(agents_progress, "error", progress_pct, f"分析失败: {str(e)}")

        result["timestamp"] = datetime.now().isoformat()
        self._analysis_started_at = None
        return result

    @property
    def graph(self) -> TradingAgentsGraph:
        """Lazy initialization of TradingAgentsGraph."""
        if self._graph is None:
            self._graph = TradingAgentsGraph(
                selected_analysts=self.analysts,
                debug=False,  # Non-interactive mode
                config=self.config,
                callbacks=None,
                fast_mode=self.fast_mode,
            )
        return self._graph

    def run(self) -> Dict[str, Any]:
        """
        Run the TradingAgents analysis workflow.
        
        Returns:
            Dict containing:
                - status: "success" or "error"
                - progress_pct: Progress percentage (0-100)
                - agents_progress: Dict mapping agent name to status
                - current_agent: Name of currently executing agent
                - final_state: Full final state from graph
                - signal: Processed trading signal
                - error: Error message if status is "error"
                - timestamp: ISO format timestamp of completion
        """
        return self._run_graph_with_progress()

    def _extract_llm_streams_from_state(self, state: Any) -> None:
        """Extract per-agent LLM outputs from the final graph state.

        This is the most reliable extraction method — final_state contains
        ALL fields written by all agents during the graph execution.
        """
        serialized = self._serialize_state(state) if not isinstance(state, dict) else state
        if not isinstance(serialized, dict):
            return

        # Map step_id (display name) to state field names
        STREAM_FIELD_MAP = {
            "market_index_analyst": "market_index_report",
            "market_analyst": "market_report",
            "sentiment_analyst": "sentiment_report",
            "news_analyst": "news_report",
            "fundamentals_analyst": "fundamentals_report",
            "persona_agents": "persona_report",
            "research_manager": "investment_plan",
            "trader": "trader_investment_plan",
            "portfolio_manager": "final_trade_decision",
        }

        for step_id, field in STREAM_FIELD_MAP.items():
            value = serialized.get(field)
            if value and isinstance(value, str) and value.strip():
                # Truncate long reports for storage
                if len(value) > self.REPORT_MAX_CHARS:
                    value = value[:self.REPORT_MAX_CHARS] + "\n...[已截断]"
                # Preserve existing content if it's more complete (real-time capture)
                existing = self._llm_streams.get(step_id, "")
                if not existing or len(value) > len(existing):
                    self._llm_streams[step_id] = value

        # Extract debate state summaries if available
        for debate_key, debate_step_id in [
            ("investment_debate_state", "research_debate"),
            ("risk_debate_state", "risk_debate"),
        ]:
            debate_value = serialized.get(debate_key)
            if isinstance(debate_value, dict):
                parts = []
                for history_key in ["bull_history", "bear_history",
                                   "aggressive_history", "conservative_history", "neutral_history"]:
                    history = debate_value.get(history_key)
                    if history and isinstance(history, str) and history.strip():
                        parts.append(f"### {history_key}\n{history[:self.REPORT_MAX_CHARS]}")
                if parts:
                    new_value = "\n\n".join(parts)
                    existing = self._llm_streams.get(debate_step_id, "")
                    if not existing or len(new_value) > len(existing):
                        self._llm_streams[debate_step_id] = new_value

    def _extract_structured_metrics(self, state: Any, signal: Any) -> Dict[str, Any]:
        """Extract structured confidence/risk metadata from final state."""
        serialized = self._serialize_state(state)
        metrics: Dict[str, Any] = {
            "analysis_type": "quick" if self.fast_mode else "full",
            "confidence": None,
            "risk_level": None,
            "market_alert": None,
        }

        if isinstance(signal, dict):
            confidence = signal.get("confidence")
            if confidence is not None:
                try:
                    metrics["confidence"] = float(confidence)
                except (TypeError, ValueError):
                    metrics["confidence"] = None

        risk_state = serialized.get("risk_debate_state") if isinstance(serialized, dict) else None
        judge_decision = risk_state.get("judge_decision") if isinstance(risk_state, dict) else None
        parsed = self._extract_json_payload(judge_decision) if isinstance(judge_decision, str) else None

        if parsed:
            risk_level = str(parsed.get("risk_level") or "").lower()
            if risk_level in {"low", "medium", "high"}:
                metrics["risk_level"] = risk_level

            confidence = parsed.get("confidence")
            try:
                if confidence is not None:
                    metrics["confidence"] = max(0.0, min(float(confidence), 1.0))
            except (TypeError, ValueError):
                pass

            market_alert = parsed.get("market_alert")
            if market_alert:
                metrics["market_alert"] = str(market_alert)

        final_text = "\n".join(
            str(part)
            for part in [
                serialized.get("final_trade_decision", "") if isinstance(serialized, dict) else "",
                judge_decision or "",
            ]
            if part
        )

        if metrics["risk_level"] is None:
            metrics["risk_level"] = self._infer_risk_level(final_text)
        if metrics["confidence"] is None:
            metrics["confidence"] = self._infer_confidence(final_text)

        return metrics

    def _extract_json_payload(self, content: str) -> Optional[Dict[str, Any]]:
        """Extract a JSON object from free-form text."""
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        candidates = [text]
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            candidates.append(match.group(0))

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                continue
        return None

    def _infer_confidence(self, text: str) -> Optional[float]:
        """Infer confidence from percentage text when structured data is unavailable."""
        if not text:
            return None

        match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
        if not match:
            return None

        try:
            value = float(match.group(1)) / 100.0
        except ValueError:
            return None
        return max(0.0, min(value, 1.0))

    def _infer_risk_level(self, text: str) -> Optional[str]:
        """Infer risk level from English/Chinese keywords."""
        if not text:
            return None

        lowered = text.lower()
        if "high risk" in lowered or "高风险" in text:
            return "high"
        if "low risk" in lowered or "低风险" in text:
            return "low"
        if "medium risk" in lowered or "中风险" in text:
            return "medium"
        return None

    def _build_slim_final_state(self, state: Any) -> Dict[str, Any]:
        """Build a compact final_state payload suitable for JSONB storage."""
        serialized = self._serialize_state(state)
        if not isinstance(serialized, dict):
            return {}

        slim_state: Dict[str, Any] = {}

        for key in [
            "company_of_interest",
            "trade_date",
            "final_trade_decision",
            "investment_plan",
            "trader_investment_plan",
        ]:
            if key in serialized:
                slim_state[key] = serialized[key]

        for report_key in [
            "market_report",
            "sentiment_report",
            "news_report",
            "fundamentals_report",
            "market_index_report",
            "persona_report",
        ]:
            report_value = serialized.get(report_key)
            if report_value is not None:
                if not isinstance(report_value, str):
                    report_value = str(report_value)
                slim_state[report_key] = self._truncate_string(
                    report_value,
                    self.REPORT_MAX_CHARS,
                )

        for debate_key in ["investment_debate_state", "risk_debate_state"]:
            debate_value = serialized.get(debate_key)
            if isinstance(debate_value, dict) and "judge_decision" in debate_value:
                judge_decision = debate_value.get("judge_decision")
                if isinstance(judge_decision, str):
                    judge_decision = self._truncate_string(
                        judge_decision,
                        self.REPORT_MAX_CHARS,
                    )
                slim_state[debate_key] = {"judge_decision": judge_decision}

        # Extract persona_signals (per-persona signal/confidence/reasoning)
        persona_signals = serialized.get("persona_signals")
        if isinstance(persona_signals, dict) and persona_signals:
            slim_state["persona_signals"] = persona_signals

        return slim_state

    def _classify_error(self, exception: Exception) -> str:
        """Classify error type for structured error reporting.
        
        Categorizes exceptions into well-defined error types for proper
        handling and retry decisions at the queue level.
        
        Args:
            exception: The caught exception
            
        Returns:
            Error type string: llm_timeout, api_error, data_error, or unknown
        """
        exception_type = type(exception).__name__
        exception_msg = str(exception).lower()
        
        # LLM Timeout errors from TimeoutWrapper
        if isinstance(exception, TimeoutError):
            return "llm_timeout"
        
        # Check for timeout-related keywords in message
        if "timeout" in exception_msg or "timed out" in exception_msg:
            return "llm_timeout"
        
        # API errors (rate limits, auth, connection)
        if exception_type in [
            "APIError", "APIConnectionError", "RateLimitError",
            "AuthenticationError", "PermissionDeniedError",
        ]:
            return "api_error"
        
        # Check for common API error patterns
        if any(keyword in exception_msg for keyword in [
            "rate limit", "api key", "authentication", "unauthorized",
            "forbidden", "connection error", "bad gateway", "service unavailable"
        ]):
            return "api_error"
        
        # Data errors (missing data, invalid symbols, etc.)
        if any(keyword in exception_msg for keyword in [
            "no data", "data not found", "invalid symbol", "symbol not found",
            "data error", "fetch failed", "unable to retrieve"
        ]):
            return "data_error"
        
        # Default to unknown for unclassified errors
        return "unknown"

    def _serialize_state(self, state: Any, max_depth: int = SERIALIZE_MAX_DEPTH) -> Dict[str, Any]:
        """
        Serialize the final state for JSON output.
        
        Args:
            state: The final state from graph.propagate
            max_depth: Maximum recursion depth for defensive traversal
            
        Returns:
            Serializable dictionary representation
        """
        if state is None:
            return {}

        raw_state: Any
        if hasattr(state, "__dict__"):
            raw_state = vars(state)
        else:
            raw_state = state

        serialized = self._to_serializable(raw_state, depth=0, max_depth=max_depth)
        if isinstance(serialized, dict):
            return serialized
        return {"raw": serialized}

    def _truncate_string(self, value: str, limit: int) -> str:
        """Truncate string to the specified character limit."""
        if len(value) <= limit:
            return value
        return value[:limit]

    def _to_serializable(self, value: Any, depth: int, max_depth: int) -> Any:
        """
        Recursively convert values into JSON-serializable primitives.
        
        Skips large message histories and limits traversal depth defensively.
        """
        if isinstance(value, str):
            return self._truncate_string(value, self.SERIALIZE_STRING_MAX_CHARS)

        if isinstance(value, (int, float, bool, type(None))):
            return value

        if depth >= max_depth:
            return "<max-depth-reached>"

        if isinstance(value, dict):
            result: Dict[str, Any] = {}
            for key, item in value.items():
                if str(key) == "messages":
                    continue
                result[str(key)] = self._to_serializable(item, depth + 1, max_depth)
            return result

        if isinstance(value, (list, tuple)):
            return [
                self._to_serializable(item, depth + 1, max_depth)
                for item in value
            ]

        if hasattr(value, "__dict__"):
            return self._to_serializable(vars(value), depth + 1, max_depth)

        return f"<{type(value).__name__}>"

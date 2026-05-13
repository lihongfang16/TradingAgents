# TradingAgents/graph/setup.py

from typing import Any, Dict
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: Dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic

    def _register_persona_nodes(
        self,
        workflow,
        enable_personas: bool,
        fast_mode: bool,
        last_clear_node: str,
    ) -> str:
        """Register persona agent nodes and return the name of the last node in the chain.

        If personas are disabled or fast_mode is active, connects ``last_clear_node``
        directly to "Bull Researcher" (or "Quick Risk Check") and returns that node.

        Otherwise registers 6 persona agents + aggregator with fan-out / fan-in
        edges and returns "Persona Aggregator".
        """
        if fast_mode or not enable_personas:
            workflow.add_edge(last_clear_node, "Quick Risk Check" if fast_mode else "Bull Researcher")
            return last_clear_node

        # Create persona agent nodes
        persona_names = [
            ("Warren Buffett", create_warren_buffett),
            ("Michael Burry", create_michael_burry),
            ("Nassim Taleb", create_nassim_taleb),
            ("Stanley Druckenmiller", create_stanley_druckenmiller),
            ("Cathie Wood", create_cathie_wood),
            ("Charlie Munger", create_charlie_munger),
        ]

        for display_name, factory in persona_names:
            workflow.add_node(display_name, factory(self.quick_thinking_llm))

        workflow.add_node("Persona Aggregator", create_persona_aggregator(self.quick_thinking_llm))

        # Fan-out: last analyst → all 6 personas
        for display_name, _ in persona_names:
            workflow.add_edge(last_clear_node, display_name)

        # Fan-in: all 6 personas → aggregator
        for display_name, _ in persona_names:
            workflow.add_edge(display_name, "Persona Aggregator")

        # Aggregator → Bull Researcher
        workflow.add_edge("Persona Aggregator", "Bull Researcher")

        return "Persona Aggregator"

    def setup_graph(
        self,
        selected_analysts=["market_index", "market", "social", "news", "fundamentals"],
        fast_mode: bool = False,
        enable_personas: bool = True,
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
        """
        if len(selected_analysts) == 0:
            raise ValueError("Trading Agents Graph Setup Error: no analysts selected!")

        # Create analyst nodes
        analyst_nodes = {}
        delete_nodes = {}
        tool_nodes = {}

        # Market Index Analyst — registered with explicit names (not via dynamic loop
        # because "market_index".capitalize() would produce "Market_index" not "Market Index")
        if "market_index" in selected_analysts:
            analyst_nodes["market_index"] = create_market_index_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["market_index"] = create_msg_delete()
            tool_nodes["market_index"] = self.tool_nodes["market_index"]

        if "market" in selected_analysts:
            analyst_nodes["market"] = create_market_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["market"] = create_msg_delete()
            tool_nodes["market"] = self.tool_nodes["market"]

        if "social" in selected_analysts:
            # "social" selector key preserved for back-compat with existing
            # user configs; the underlying agent has been renamed to
            # sentiment_analyst (the old name advertised social-media data
            # the agent never had access to — see issue #557).
            analyst_nodes["social"] = create_sentiment_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["social"] = create_msg_delete()
            tool_nodes["social"] = self.tool_nodes["social"]

        if "news" in selected_analysts:
            analyst_nodes["news"] = create_news_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["news"] = create_msg_delete()
            tool_nodes["news"] = self.tool_nodes["news"]

        if "fundamentals" in selected_analysts:
            analyst_nodes["fundamentals"] = create_fundamentals_analyst(
                self.quick_thinking_llm
            )
            delete_nodes["fundamentals"] = create_msg_delete()
            tool_nodes["fundamentals"] = self.tool_nodes["fundamentals"]

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph
        for analyst_type, node in analyst_nodes.items():
            # market_index uses explicit node names "Market Index Analyst" etc., skip here
            if analyst_type == "market_index":
                continue
            workflow.add_node(f"{analyst_type.capitalize()} Analyst", node)
            workflow.add_node(
                f"Msg Clear {analyst_type.capitalize()}", delete_nodes[analyst_type]
            )
            workflow.add_node(f"tools_{analyst_type}", tool_nodes[analyst_type])

        # Register Market Index Analyst with explicit names
        if "market_index" in selected_analysts:
            workflow.add_node("Market Index Analyst", analyst_nodes["market_index"])
            workflow.add_node("Msg Clear Market Index", delete_nodes["market_index"])
            workflow.add_node("tools_market_index", tool_nodes["market_index"])

        # Add other nodes
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)

        if fast_mode:
            workflow.add_node("Quick Risk Check", quick_risk_check_node)
        else:
            workflow.add_node("Bull Researcher", bull_researcher_node)
            workflow.add_node("Bear Researcher", bear_researcher_node)
            workflow.add_node("Research Manager", research_manager_node)
            workflow.add_node("Aggressive Analyst", aggressive_analyst)
            workflow.add_node("Neutral Analyst", neutral_analyst)
            workflow.add_node("Conservative Analyst", conservative_analyst)

        # Define edges
        # Start with the first analyst
        first_analyst = selected_analysts[0]
        if first_analyst == "market_index":
            workflow.add_edge(START, "Market Index Analyst")
        else:
            workflow.add_edge(START, f"{first_analyst.capitalize()} Analyst")

        # Connect analysts in sequence
        for i, analyst_type in enumerate(selected_analysts):
            # market_index uses explicit node names
            if analyst_type == "market_index":
                current_analyst = "Market Index Analyst"
                current_tools = "tools_market_index"
                current_clear = "Msg Clear Market Index"
                should_continue = "should_continue_market_index"
            else:
                current_analyst = f"{analyst_type.capitalize()} Analyst"
                current_tools = f"tools_{analyst_type}"
                current_clear = f"Msg Clear {analyst_type.capitalize()}"
                should_continue = f"should_continue_{analyst_type}"

            # Add conditional edges for current analyst
            workflow.add_conditional_edges(
                current_analyst,
                getattr(self.conditional_logic, should_continue),
                [current_tools, current_clear],
            )
            workflow.add_edge(current_tools, current_analyst)

            # Connect to next analyst or delegate to persona registration
            if i < len(selected_analysts) - 1:
                next_type = selected_analysts[i + 1]
                next_analyst = "Market Index Analyst" if next_type == "market_index" else f"{next_type.capitalize()} Analyst"
                workflow.add_edge(current_clear, next_analyst)
            else:
                # Last analyst → persona nodes (or directly to Bull Researcher if personas disabled)
                last_clear_node = current_clear

        # Register persona agents (or skip edge to Bull Researcher)
        self._register_persona_nodes(workflow, enable_personas, fast_mode, last_clear_node)

        if fast_mode:
            workflow.add_edge("Quick Risk Check", "Trader")
            workflow.add_edge("Trader", "Portfolio Manager")
            workflow.add_edge("Portfolio Manager", END)
            return workflow.compile()

        # Add remaining edges
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )

        workflow.add_edge("Portfolio Manager", END)

        return workflow

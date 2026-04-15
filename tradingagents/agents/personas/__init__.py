"""
Investor persona agents for A-share market analysis.

Each persona embodies a distinct investment philosophy and provides
structured signals (bullish/bearish/neutral) with confidence scores.
"""
from .warren_buffett import create_warren_buffett
from .michael_burry import create_michael_burry
from .nassim_taleb import create_nassim_taleb
from .stanley_druckenmiller import create_stanley_druckenmiller
from .cathie_wood import create_cathie_wood
from .charlie_munger import create_charlie_munger
from .aggregator import create_persona_aggregator
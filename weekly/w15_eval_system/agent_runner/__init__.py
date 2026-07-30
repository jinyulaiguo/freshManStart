"""Day 105 Agent runners: live ResearchAgent adapter + mock Trace runner."""

from __future__ import annotations

import os
import sys

_W15_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _W15_ROOT not in sys.path:
    sys.path.append(_W15_ROOT)

from .mock_runner import MockTraceRunner
from .research_adapter import ResearchAgentTraceAdapter

__all__ = ["MockTraceRunner", "ResearchAgentTraceAdapter"]

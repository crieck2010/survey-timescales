"""survey-timescales: timeframe-selection engine for the remote-sensing suite.

Suggest the right ``[start, end]`` window for a map reel before fetching a
single byte: annual cycles, climatological seasons, event-density bands,
and multi-year trend horizons — all from a curated registry shipped with
the package, optionally refined by data-driven period detection.

Fully deterministic: no network, no LLM, no UI imports.
``numpy`` + the standard library only.
"""

from .detect import DominantPeriod, detect_dominant_period
from .framing import MODES, WindowSuggestion, suggest_window, trim_lulls
from .registry import (RegistryEntry, StaticVariableError, TimescaleRegistry,
                       UnknownVariableError, canonical_variable, load_registry)
from .stride import recommend_stride

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "suggest_window",
    "recommend_stride",
    "detect_dominant_period",
    "load_registry",
    "WindowSuggestion",
    "DominantPeriod",
    "RegistryEntry",
    "TimescaleRegistry",
    "trim_lulls",
    "canonical_variable",
    "MODES",
    "UnknownVariableError",
    "StaticVariableError",
]

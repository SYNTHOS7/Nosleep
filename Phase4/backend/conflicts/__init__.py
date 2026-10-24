"""
Conflicts package initialization.
"""

from backend.conflicts.detector import (
    find_conflicts,
    EXCLUSIVE_PREDICATES,
    PLANTED_INCOMPATIBLE_PAIRS,
)

__all__ = [
    "find_conflicts",
    "EXCLUSIVE_PREDICATES",
    "PLANTED_INCOMPATIBLE_PAIRS",
]

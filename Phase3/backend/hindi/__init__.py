"""
Hindi evaluation package initialization.
"""

from backend.hindi.evaluator import (
    FROZEN_HINDI_EVAL_SET,
    evaluate_hindi_retrieval_routes,
    simple_hindi_to_english_translation,
)

__all__ = [
    "FROZEN_HINDI_EVAL_SET",
    "evaluate_hindi_retrieval_routes",
    "simple_hindi_to_english_translation",
]

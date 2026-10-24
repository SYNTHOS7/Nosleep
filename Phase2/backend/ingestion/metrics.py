"""Throughput metrics and stage timing tracker for durable operations and benchmark runs."""

import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StageTimer:
    """Context manager or manual recorder for stage execution times."""

    def __init__(self, stage_name: str, metrics_tracker: "OperationMetricsTracker"):
        self.stage_name = stage_name
        self.tracker = metrics_tracker
        self.start_time: float = 0.0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.perf_counter() - self.start_time
        self.tracker.record_stage_time(self.stage_name, duration)


class OperationMetricsTracker(BaseModel):
    """Tracks latency, stage timing, resource counts, and throughput metrics for an operation."""
    operation_id: str
    accepted_time: float = Field(default_factory=time.time)
    ready_time: Optional[float] = None
    total_latency_seconds: Optional[float] = None
    stage_durations: Dict[str, float] = Field(default_factory=dict)

    # Resource counts
    byte_count: int = 0
    page_count: int = 0
    chunk_count: int = 0
    entity_count: int = 0
    relation_count: int = 0
    value_count: int = 0
    vector_count: int = 0

    # Model and cache telemetry
    llm_calls: int = 0
    llm_tokens: int = 0
    retries_count: int = 0
    cache_hits: int = 0
    failure_reason: Optional[str] = None

    def time_stage(self, stage_name: str) -> StageTimer:
        return StageTimer(stage_name, self)

    def record_stage_time(self, stage_name: str, duration: float):
        self.stage_durations[stage_name] = round(duration, 4)

    def mark_ready(self):
        self.ready_time = time.time()
        self.total_latency_seconds = round(self.ready_time - self.accepted_time, 4)

    def is_within_deadline(self, deadline_seconds: float = 60.0) -> bool:
        if self.total_latency_seconds is None:
            return False
        return self.total_latency_seconds <= deadline_seconds

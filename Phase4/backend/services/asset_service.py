"""Analyst-supplied asset context and transparent route triage; no exploitability scoring."""
from datetime import datetime, timezone
import hashlib
import threading
import uuid
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.storage.vector_store import get_vector_store
from backend.services.attack_path_service import trace_attack_paths


class AssetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    criticality: Literal["unknown", "low", "medium", "high", "critical"] = "unknown"
    exposure: Literal["unknown", "internet", "internal", "isolated"] = "unknown"
    owner: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=2000)
    expected_version: int = Field(default=0, ge=0, le=2147483646)
    expected_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @model_validator(mode="after")
    def require_token(self):
        if self.expected_version > 0 and not self.expected_token:
            raise ValueError("Updates require the current asset token")
        return self

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Use a nonempty asset name without control characters")
        return value


class AssetConflictError(RuntimeError):
    pass


class MemoryAssets:
    def __init__(self):
        self.records, self.lock = {}, threading.RLock()

    def list_assets(self, workspace):
        with self.lock:
            return [dict(value) for (ws, _), value in self.records.items() if ws == workspace]

    def write_asset(self, workspace, record, expected):
        with self.lock:
            current = self.records.get((workspace, record["id"]))
            if (current["version"] if current else 0) != expected or (current and current["revision_token"] != record["revision_token"]):
                return False
            self.records[workspace, record["id"]] = dict(record)
            return True

    def delete_asset(self, workspace, identifier, expected, token):
        with self.lock:
            record = self.records.get((workspace, identifier))
            if not record or record["version"] != expected or record["revision_token"] != token:
                return False
            del self.records[workspace, identifier]
            return True


_memory = MemoryAssets()


def repository():
    persistence = getattr(get_vector_store(), "persistence", None)
    return persistence if persistence else _memory


def save_asset(workspace, value, actor, store=None):
    store = store or repository()
    identifier = "asset-" + hashlib.sha256(value.name.casefold().encode()).hexdigest()[:24]
    record = {**value.model_dump(exclude={"expected_version", "expected_token"}), "id": identifier,
              "version": value.expected_version + 1, "workspace_id": workspace,
              "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": actor,
              "source_kind": "analyst_supplied", "revision_token": value.expected_token if value.expected_version else uuid.uuid4().hex}
    if not store.write_asset(workspace, record, value.expected_version):
        raise AssetConflictError("Asset changed or already exists. Refresh before saving.")
    return record


def assess_routes(workspace, entry_point, store=None, graph=None):
    records = (store or repository()).list_assets(workspace)
    inventory = {record["name"].casefold(): record for record in records}
    trace = trace_attack_paths(workspace, entry_point, 3, graph)
    entry = inventory.get(entry_point.casefold())
    ranked = []
    for route in trace["paths"]:
        target = inventory.get(route["nodes"][-1].casefold())
        criticality = target["criticality"] if target else "unknown"
        exposure = entry["exposure"] if entry else "unknown"
        priority = "unassessed" if criticality == "unknown" else (
            "review_first" if criticality in {"high", "critical"} or (criticality == "medium" and exposure == "internet") else "review_next")
        missing = []
        if criticality == "unknown": missing.append("target criticality")
        if exposure == "unknown": missing.append("entry exposure")
        reasons = [f"Analyst-declared target criticality: {criticality}.", f"Analyst-declared entry exposure: {exposure}."]
        if exposure == "isolated": reasons.append("Declared isolation may conflict with the cited connectivity; verify both.")
        ranked.append({**route, "review_priority": priority, "target_asset": target, "entry_asset": entry,
                       "context_source": "analyst_supplied_unverified", "missing_context": missing, "reasons": reasons,
                       "exploitability": "not_determined"})
    band = {"review_first": 0, "unassessed": 1, "review_next": 2}
    impact = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}
    ranked.sort(key=lambda route: (band[route["review_priority"]], impact[(route["target_asset"] or {}).get("criticality", "unknown")], route["path_id"]))
    return {"workspace_id": workspace, "entry_point": entry_point, "routes": ranked,
            "method": "review-order-v1", "validation_checklist": [
                "Verify that the cited connectivity is current.",
                "Confirm installed software versions, patch status and exploit prerequisites.",
                "Check required privileges, credentials and effective network controls."],
            "limitations": trace["limitations"] + " Priority is an ordinal review aid based on unverified analyst input, not CVSS, probability or proof of exploitability. No remediation is executed."}

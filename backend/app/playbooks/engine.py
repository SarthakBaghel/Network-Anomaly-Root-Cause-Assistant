from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
PLAYBOOKS_FILE = FIXTURES_DIR / "playbooks.yaml"

DIAGNOSTIC_STEP_TYPE = "diagnostic"
REMEDIATION_STEP_TYPE = "remediation"
VALID_STEP_TYPES = (DIAGNOSTIC_STEP_TYPE, REMEDIATION_STEP_TYPE)


class PlaybookValidationError(Exception):
    """Raised at startup when a playbook fixture violates a safety invariant."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class PlaybookRecommendation(BaseModel):
    step_id: str
    title: str
    step_type: Literal["diagnostic", "remediation"]
    applicable_hypothesis_types: list[str]
    applicable_entity_types: list[str]
    preconditions: list[str] = []
    instructions: list[str]
    risk_level: str
    rollback_note: str | None = None
    requires_human_approval: bool


def _load_raw() -> dict:
    with open(PLAYBOOKS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Legacy helpers (consumed by app.explanation.service). Preserved for
# backward compatibility; they read the top-level ``playbooks`` block.
# ---------------------------------------------------------------------------
def load_playbooks() -> list[dict]:
    return _load_raw().get("playbooks", [])


def find_playbook_for_entity(candidate_entity: str) -> dict | None:
    for playbook in load_playbooks():
        if playbook["matches_entity"] == candidate_entity:
            return playbook
    return None


def get_step(playbook_step_id: str) -> dict | None:
    for playbook in load_playbooks():
        for step in playbook["steps"]:
            if step["step_id"] == playbook_step_id:
                return step
    return None


# ---------------------------------------------------------------------------
# Playbook Engine (P5-01 / P5-02)
# ---------------------------------------------------------------------------
def _validate_recommendations(recommendations: list[PlaybookRecommendation]) -> None:
    """Enforce safety invariants on the loaded recommendations.

    Invariants:
    - step_type must be one of VALID_STEP_TYPES.
    - every remediation step MUST require human approval.
    """
    errors: list[str] = []
    for rec in recommendations:
        if rec.step_type not in VALID_STEP_TYPES:
            errors.append(
                f"step '{rec.step_id}' has unknown step_type '{rec.step_type}'"
            )
        if rec.step_type == REMEDIATION_STEP_TYPE and not rec.requires_human_approval:
            errors.append(
                f"remediation step '{rec.step_id}' must set "
                f"requires_human_approval=true"
            )
    if errors:
        raise PlaybookValidationError(errors)


@lru_cache(maxsize=1)
def load_recommendations() -> tuple[PlaybookRecommendation, ...]:
    """Load, validate, and cache the structured recommendation steps.

    Raises ``PlaybookValidationError`` if any remediation step is missing
    human-approval gating.
    """
    raw = _load_raw().get("recommendations", []) or []
    recommendations = [PlaybookRecommendation(**entry) for entry in raw]
    _validate_recommendations(recommendations)
    return tuple(recommendations)


def get_recommendations(
    hypothesis_type: str,
    entity_type: str,
) -> list[PlaybookRecommendation]:
    """Return recommendations matching both hypothesis type and entity type.

    An unknown ``hypothesis_type`` (one that matches no recommendation) yields
    an empty list.
    """
    return [
        rec
        for rec in load_recommendations()
        if hypothesis_type in rec.applicable_hypothesis_types
        and entity_type in rec.applicable_entity_types
    ]


# Validate fixtures at import time so a bad playbook fails fast at startup.
load_recommendations()

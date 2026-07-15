from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    """A human-approved, catalogue-backed diagnostic or remediation step."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    title: str
    step_type: Literal["diagnostic", "remediation"]
    applicable_hypothesis_types: list[str] = Field(min_length=1)
    applicable_entity_types: list[str] = Field(min_length=1)
    preconditions: list[str]
    instructions: list[str] = Field(min_length=1)
    risk_level: Literal["low", "medium", "high"]
    rollback_note: str | None
    requires_human_approval: bool


def _load_raw() -> dict:
    with open(PLAYBOOKS_FILE, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise PlaybookValidationError(
            ["playbooks fixture must contain a YAML mapping"]
        )
    return raw


# ---------------------------------------------------------------------------
# Compatibility helpers for catalogue consumers that need a raw dictionary.
# ---------------------------------------------------------------------------
def load_playbooks() -> list[dict]:
    return [
        recommendation.model_dump(mode="json")
        for recommendation in load_recommendations()
    ]


def find_playbook_for_entity(candidate_entity: str) -> dict | None:
    for playbook in load_playbooks():
        if candidate_entity in playbook["applicable_entity_types"]:
            return playbook
    return None


def get_step(playbook_step_id: str) -> dict | None:
    for playbook in load_playbooks():
        if playbook["step_id"] == playbook_step_id:
            return playbook
    return None


# ---------------------------------------------------------------------------
# Playbook Engine (P5-01 / P5-02)
# ---------------------------------------------------------------------------
def _validate_recommendations(recommendations: list[PlaybookRecommendation]) -> None:
    """Enforce safety invariants on the loaded recommendations.

    Invariants:
    - step_type must be one of VALID_STEP_TYPES.
    - every catalogue step MUST require human approval.
    """
    errors: list[str] = []
    for rec in recommendations:
        if rec.step_type not in VALID_STEP_TYPES:
            errors.append(
                f"step '{rec.step_id}' has unknown step_type '{rec.step_type}'"
            )
        if not rec.requires_human_approval:
            errors.append(
                f"playbook step '{rec.step_id}' must set "
                f"requires_human_approval=true"
            )
    if errors:
        raise PlaybookValidationError(errors)


@lru_cache(maxsize=1)
def load_recommendations() -> tuple[PlaybookRecommendation, ...]:
    """Load, validate, and cache the structured recommendation steps.

    Raises ``PlaybookValidationError`` when the fixture is malformed or any
    catalogue step is missing human-approval gating.
    """
    raw = _load_raw().get("steps")
    if not isinstance(raw, list) or not raw:
        raise PlaybookValidationError(
            ["playbooks fixture must contain a non-empty 'steps' list"]
        )

    try:
        recommendations = [PlaybookRecommendation(**entry) for entry in raw]
    except (TypeError, ValidationError) as exc:
        raise PlaybookValidationError([f"invalid playbook step: {exc}"]) from exc
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

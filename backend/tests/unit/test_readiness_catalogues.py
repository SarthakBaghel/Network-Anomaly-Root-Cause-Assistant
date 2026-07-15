from __future__ import annotations

from copy import deepcopy

import pytest

from app import readiness


def _catalogues() -> dict[str, dict]:
    return {
        name: readiness._load(readiness.FIXTURE_ROOT / name)
        for name in readiness.CATALOGUES
    }


def _install_catalogues(monkeypatch: pytest.MonkeyPatch, payloads: dict[str, dict]) -> None:
    monkeypatch.setattr(
        readiness,
        "_load",
        lambda path: deepcopy(payloads[path.name]),
    )


def test_catalogue_status_rejects_duplicate_playbook_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _catalogues()
    payloads["playbooks.yaml"]["steps"].append(
        deepcopy(payloads["playbooks.yaml"]["steps"][0])
    )
    _install_catalogues(monkeypatch, payloads)

    with pytest.raises(ValueError, match="present and unique"):
        readiness.catalogue_status()


def test_catalogue_status_rejects_missing_declared_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _catalogues()
    payloads["hypotheses.yaml"]["hypotheses"][0]["diagnostic_step_ids"][0] = (
        "missing-step"
    )
    _install_catalogues(monkeypatch, payloads)

    with pytest.raises(ValueError, match="references unknown step"):
        readiness.catalogue_status()


def test_catalogue_status_rejects_incompatible_declared_step_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _catalogues()
    hypothesis = payloads["hypotheses.yaml"]["hypotheses"][0]
    step_id = hypothesis["diagnostic_step_ids"][0]
    step = next(
        item for item in payloads["playbooks.yaml"]["steps"] if item["step_id"] == step_id
    )
    step["step_type"] = "remediation"
    _install_catalogues(monkeypatch, payloads)

    with pytest.raises(ValueError, match="declared as diagnostic"):
        readiness.catalogue_status()


def test_load_rejects_unsupported_catalogue_version(tmp_path) -> None:
    path = tmp_path / "topology.json"
    path.write_text(
        '{"schema_version":"1.0","version":"topology-99.0"}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported schema/version"):
        readiness._load(path)

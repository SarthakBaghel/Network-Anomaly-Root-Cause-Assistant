import json
from datetime import datetime, timezone
from pathlib import Path

from app.contracts import AuditRecord, InvestigationResponse
from app.reporting import handover_filename, render_handover_markdown, render_handover_pdf


FIXTURES = Path(__file__).resolve().parent / "fixtures"
GENERATED_AT = datetime(2026, 7, 16, 0, 15, 30, tzinfo=timezone.utc)


def _snapshot() -> InvestigationResponse:
    return InvestigationResponse.model_validate(
        json.loads((FIXTURES / "golden_investigation_response.json").read_text(encoding="utf-8"))
    )


def _audits() -> list[AuditRecord]:
    payload = json.loads((FIXTURES / "golden_audit_examples.json").read_text(encoding="utf-8"))
    return [AuditRecord.model_validate(item) for item in payload["records"]]


def test_markdown_handover_contains_operational_sections_and_snapshot_identity():
    snapshot = _snapshot()
    report = render_handover_markdown(snapshot, _audits(), generated_at=GENERATED_AT)

    assert report.startswith("# Incident Shift Handover")
    assert snapshot.analysis_run_id in report
    assert snapshot.incident.title in report
    assert "## Incident Timeline" in report
    assert "## Top-Ranked Hypothesis" in report
    assert "## Evidence" in report
    assert "## Actions Taken" in report
    assert "## Audit Trail" in report
    assert snapshot.explanation.summary in report
    assert report.index("2026-07-14 09:32:01 UTC") < report.index("2026-07-14 09:32:03 UTC")


def test_reportlab_pdf_is_a_nonempty_pdf_with_stable_metadata_filename():
    snapshot = _snapshot()
    report = render_handover_pdf(snapshot, _audits(), generated_at=GENERATED_AT)

    assert report.startswith(b"%PDF-")
    assert len(report) > 5_000
    assert handover_filename(snapshot, GENERATED_AT, "pdf") == (
        f"incident-{snapshot.incident.incident_id}-shift-handover-20260716T001530Z.pdf"
    )

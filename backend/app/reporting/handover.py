from __future__ import annotations

import html
import io
import re
import unicodedata
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.contracts import AuditRecord, InvestigationResponse


NAVY = colors.HexColor("#0B1220")
SLATE = colors.HexColor("#334155")
MUTED = colors.HexColor("#64748B")
CYAN = colors.HexColor("#0891B2")
PALE_CYAN = colors.HexColor("#ECFEFF")
PALE_SLATE = colors.HexColor("#F8FAFC")
BORDER = colors.HexColor("#CBD5E1")
RED = colors.HexColor("#B91C1C")
AMBER = colors.HexColor("#B45309")
GREEN = colors.HexColor("#047857")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).strftime("%Y-%m-%d %H:%M:%S UTC")


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _human(value: object) -> str:
    raw = value.value if isinstance(value, Enum) else value
    return str(raw).replace("_", " ").strip().title()


def _ascii(value: object) -> str:
    text = str(value).translate(
        str.maketrans(
            {
                "\u2010": "-",
                "\u2011": "-",
                "\u2012": "-",
                "\u2013": "-",
                "\u2014": "-",
                "\u2018": "'",
                "\u2019": "'",
                "\u201c": '"',
                "\u201d": '"',
                "\u2026": "...",
            }
        )
    )
    return unicodedata.normalize("NFKD", text).encode("ascii", "replace").decode("ascii")


def _pdf_text(value: object) -> str:
    return html.escape(_ascii(value)).replace("\n", "<br/>")


def _event_signal(item) -> str:
    event = item.event
    if event.signal_name is not None and event.signal_value is not None:
        unit = f" {event.unit}" if event.unit else ""
        return f"{event.signal_name} = {event.signal_value:g}{unit}"
    return event.event_type


def _top_hypothesis(snapshot: InvestigationResponse):
    return min(snapshot.hypotheses, key=lambda item: item.rank)


def _ordered_audit(records: Iterable[AuditRecord]) -> list[AuditRecord]:
    return sorted(records, key=lambda item: (_utc(item.timestamp), item.audit_id))


def handover_filename(
    snapshot: InvestigationResponse,
    generated_at: datetime,
    extension: str,
) -> str:
    safe_incident = re.sub(r"[^A-Za-z0-9_-]+", "-", snapshot.incident.incident_id).strip("-")
    stamp = _utc(generated_at).strftime("%Y%m%dT%H%M%SZ")
    return f"incident-{safe_incident}-shift-handover-{stamp}.{extension}"


def render_handover_markdown(
    snapshot: InvestigationResponse,
    audit_records: Sequence[AuditRecord],
    *,
    generated_at: datetime,
) -> str:
    top = _top_hypothesis(snapshot)
    evidence = snapshot.evidence_by_hypothesis.get(top.hypothesis_id, [])
    attached = [item for item in snapshot.timeline if item.attachment_decision == "attached"]
    excluded_count = len(snapshot.timeline) - len(attached)
    recommendations = snapshot.recommendations_by_hypothesis.get(top.hypothesis_id, [])
    audits = _ordered_audit(audit_records)

    lines = [
        "# Incident Shift Handover",
        "",
        f"> Generated {_iso(generated_at)} from immutable analysis run `{snapshot.analysis_run_id}`.",
        "",
        "## Incident Summary",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Incident | {_markdown_cell(snapshot.incident.title)} |",
        f"| Incident ID | `{snapshot.incident.incident_id}` |",
        f"| Status | **{_human(snapshot.incident.status)}** |",
        f"| Severity | **{snapshot.incident.severity:.2f}** |",
        f"| Started | {_iso(snapshot.incident.started_at)} |",
        f"| Last event | {_iso(snapshot.incident.last_event_at)} |",
        f"| Primary entity | `{snapshot.incident.primary_entity_id}` |",
        f"| Affected entities | {_markdown_cell(', '.join(snapshot.incident.affected_entity_ids))} |",
        "",
        snapshot.explanation.summary,
        "",
        "## Top-Ranked Hypothesis",
        "",
        f"**{_human(top.hypothesis_type)}** on `{top.candidate_entity_id}` - score **{top.evidence_score:.1f}/100**, evidence coverage **{top.evidence_coverage.available}/{top.evidence_coverage.expected}**.",
        "",
        top.summary,
        "",
        "## Evidence",
        "",
    ]
    for kind in ("observed", "correlated", "conflicting", "missing"):
        rows = [item for item in evidence if item.kind.value == kind]
        lines.extend([f"### {_human(kind)}", ""])
        if rows:
            lines.extend(
                f"- {_markdown_cell(item.statement)} (`{item.reason_code}`)" for item in rows
            )
        else:
            lines.append("- None recorded.")
        lines.append("")

    lines.extend(
        [
            "## Incident Timeline",
            "",
            "| Time | Entity | Modality | Signal | Attachment basis |",
            "|---|---|---|---|---|",
        ]
    )
    for item in attached:
        lines.append(
            "| "
            + " | ".join(
                [
                    _iso(item.event.timestamp),
                    f"`{item.event.entity_id}`",
                    _human(item.event.modality),
                    _markdown_cell(_event_signal(item)),
                    _markdown_cell(", ".join(item.attachment_reasons)),
                ]
            )
            + " |"
        )
    if not attached:
        lines.append("| - | - | - | No attached incident events | - |")
    lines.extend(
        ["", f"_Excluded contextual events: {excluded_count}._", "", "## Actions Taken", ""]
    )
    if snapshot.reviews:
        for review in sorted(snapshot.reviews, key=lambda item: (item.created_at, item.review_id)):
            comment = f" - {review.comment}" if review.comment else ""
            lines.append(
                f"- {_iso(review.created_at)} - **{_human(review.decision)}** by `{review.reviewer}` on `{review.hypothesis_id}`{_markdown_cell(comment)}"
            )
    else:
        lines.append("- No operator review actions have been recorded.")

    lines.extend(["", "## Recommended Next Actions", ""])
    if recommendations:
        for recommendation in recommendations:
            approval = (
                "human approval required"
                if recommendation.requires_human_approval
                else "pre-approved"
            )
            lines.append(
                f"- **{recommendation.title}** (`{recommendation.step_id}`, {recommendation.risk_level} risk, {approval}): {_markdown_cell(recommendation.instructions)}"
            )
    else:
        lines.append("- No catalogue recommendations are attached to the top hypothesis.")

    lines.extend(
        [
            "",
            "## Audit Trail",
            "",
            "| Timestamp | Actor | Action | Object | Request ID |",
            "|---|---|---|---|---|",
        ]
    )
    for record in audits:
        actor = f"{record.actor_type.value}:{record.actor_id or 'system'}"
        lines.append(
            "| "
            + " | ".join(
                [
                    _iso(record.timestamp),
                    _markdown_cell(actor),
                    f"`{record.action}`",
                    _markdown_cell(f"{record.object_type}:{record.object_id}"),
                    f"`{record.request_id}`",
                ]
            )
            + " |"
        )
    if not audits:
        lines.append("| - | - | No audit records available | - | - |")

    lines.extend(
        [
            "",
            "---",
            f"Snapshot revision {snapshot.analysis_run.revision}; explanation generator: `{snapshot.explanation.generator}`. Recommendations are advisory and are not automatically executed.",
            "",
        ]
    )
    return "\n".join(lines)


def _styles():
    sample = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "HandoverTitle",
            parent=sample["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=5 * mm,
        ),
        "subtitle": ParagraphStyle(
            "HandoverSubtitle",
            parent=sample["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=MUTED,
            spaceAfter=4 * mm,
        ),
        "heading": ParagraphStyle(
            "HandoverHeading",
            parent=sample["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=NAVY,
            spaceBefore=5 * mm,
            spaceAfter=2.5 * mm,
        ),
        "subheading": ParagraphStyle(
            "HandoverSubheading",
            parent=sample["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=12,
            textColor=SLATE,
            spaceBefore=2.5 * mm,
            spaceAfter=1.5 * mm,
        ),
        "body": ParagraphStyle(
            "HandoverBody",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=12,
            textColor=SLATE,
            spaceAfter=2 * mm,
        ),
        "small": ParagraphStyle(
            "HandoverSmall",
            parent=sample["BodyText"],
            fontName="Helvetica",
            fontSize=7.2,
            leading=9.5,
            textColor=SLATE,
        ),
        "small_center": ParagraphStyle(
            "HandoverSmallCenter",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.2,
            leading=9.5,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "callout": ParagraphStyle(
            "HandoverCallout",
            parent=sample["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            textColor=NAVY,
            borderColor=CYAN,
            borderWidth=1,
            borderPadding=8,
            backColor=PALE_CYAN,
            spaceAfter=4 * mm,
        ),
    }


def _paragraph(value: object, style) -> Paragraph:
    return Paragraph(_pdf_text(value), style)


def _table(data, widths, *, header: bool = False, repeat_rows: int = 0) -> LongTable:
    table = LongTable(data, colWidths=widths, repeatRows=repeat_rows, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, PALE_SLATE]),
    ]
    if header:
        commands.extend(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ]
        )
    table.setStyle(TableStyle(commands))
    return table


def render_handover_pdf(
    snapshot: InvestigationResponse,
    audit_records: Sequence[AuditRecord],
    *,
    generated_at: datetime,
) -> bytes:
    styles = _styles()
    top = _top_hypothesis(snapshot)
    evidence = snapshot.evidence_by_hypothesis.get(top.hypothesis_id, [])
    attached = [item for item in snapshot.timeline if item.attachment_decision == "attached"]
    recommendations = snapshot.recommendations_by_hypothesis.get(top.hypothesis_id, [])
    audits = _ordered_audit(audit_records)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=19 * mm,
        bottomMargin=17 * mm,
        title=f"Shift handover - {snapshot.incident.incident_id}",
        author="Network Anomaly RCA",
        subject="Incident shift handover report",
    )
    story = [
        _paragraph("INCIDENT SHIFT HANDOVER", styles["title"]),
        _paragraph(
            f"Generated {_iso(generated_at)} | Immutable analysis run {snapshot.analysis_run_id} | Revision {snapshot.analysis_run.revision}",
            styles["subtitle"],
        ),
    ]
    summary_rows = [
        [
            _paragraph("Incident", styles["small"]),
            _paragraph(snapshot.incident.title, styles["small"]),
        ],
        [
            _paragraph("Status / severity", styles["small"]),
            _paragraph(
                f"{_human(snapshot.incident.status)} / {snapshot.incident.severity:.2f}",
                styles["small"],
            ),
        ],
        [
            _paragraph("Window", styles["small"]),
            _paragraph(
                f"{_iso(snapshot.incident.started_at)} to {_iso(snapshot.incident.last_event_at)}",
                styles["small"],
            ),
        ],
        [
            _paragraph("Primary entity", styles["small"]),
            _paragraph(snapshot.incident.primary_entity_id, styles["small"]),
        ],
        [
            _paragraph("Affected entities", styles["small"]),
            _paragraph(", ".join(snapshot.incident.affected_entity_ids), styles["small"]),
        ],
    ]
    summary = Table(summary_rows, colWidths=[35 * mm, 125 * mm], hAlign="LEFT")
    summary.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), PALE_SLATE),
                ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
                ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend(
        [summary, Spacer(1, 4 * mm), _paragraph(snapshot.explanation.summary, styles["callout"])]
    )

    story.extend(
        [
            _paragraph("Top-Ranked Hypothesis", styles["heading"]),
            _paragraph(
                f"{_human(top.hypothesis_type)} on {top.candidate_entity_id} | Score {top.evidence_score:.1f}/100 | Coverage {top.evidence_coverage.available}/{top.evidence_coverage.expected}",
                styles["subheading"],
            ),
            _paragraph(top.summary, styles["body"]),
            _paragraph("Evidence", styles["heading"]),
        ]
    )
    kind_colors = {"observed": GREEN, "correlated": CYAN, "conflicting": RED, "missing": AMBER}
    for kind in ("observed", "correlated", "conflicting", "missing"):
        rows = [item for item in evidence if item.kind.value == kind]
        story.append(_paragraph(_human(kind), styles["subheading"]))
        if rows:
            data = [
                [
                    _paragraph(item.statement, styles["small"]),
                    _paragraph(item.reason_code, styles["small"]),
                ]
                for item in rows
            ]
            table = _table(data, [130 * mm, 30 * mm])
            table.setStyle(TableStyle([("LINEBEFORE", (0, 0), (0, -1), 2, kind_colors[kind])]))
            story.extend([table, Spacer(1, 1.5 * mm)])
        else:
            story.append(_paragraph("None recorded.", styles["body"]))

    story.append(_paragraph("Incident Timeline", styles["heading"]))
    timeline_data = [
        [
            _paragraph("Time", styles["small_center"]),
            _paragraph("Entity", styles["small_center"]),
            _paragraph("Type", styles["small_center"]),
            _paragraph("Signal", styles["small_center"]),
        ]
    ]
    timeline_data.extend(
        [
            _paragraph(_iso(item.event.timestamp), styles["small"]),
            _paragraph(item.event.entity_id, styles["small"]),
            _paragraph(_human(item.event.modality), styles["small"]),
            _paragraph(_event_signal(item), styles["small"]),
        ]
        for item in attached
    )
    if len(timeline_data) == 1:
        timeline_data.append(
            [_paragraph("-", styles["small"])] * 3
            + [_paragraph("No attached incident events", styles["small"])]
        )
    story.extend(
        [
            _table(timeline_data, [32 * mm, 37 * mm, 24 * mm, 67 * mm], header=True, repeat_rows=1),
            _paragraph(
                f"Excluded contextual events: {len(snapshot.timeline) - len(attached)}",
                styles["subtitle"],
            ),
            _paragraph("Actions Taken", styles["heading"]),
        ]
    )
    if snapshot.reviews:
        action_data = [
            [
                _paragraph("Time", styles["small_center"]),
                _paragraph("Operator", styles["small_center"]),
                _paragraph("Decision", styles["small_center"]),
                _paragraph("Comment", styles["small_center"]),
            ]
        ]
        action_data.extend(
            [
                _paragraph(_iso(review.created_at), styles["small"]),
                _paragraph(review.reviewer, styles["small"]),
                _paragraph(_human(review.decision), styles["small"]),
                _paragraph(review.comment or "-", styles["small"]),
            ]
            for review in sorted(
                snapshot.reviews, key=lambda item: (item.created_at, item.review_id)
            )
        )
        story.append(
            _table(action_data, [34 * mm, 28 * mm, 32 * mm, 66 * mm], header=True, repeat_rows=1)
        )
    else:
        story.append(_paragraph("No operator review actions have been recorded.", styles["body"]))

    story.append(_paragraph("Recommended Next Actions", styles["heading"]))
    if recommendations:
        recommendation_data = [
            [
                _paragraph("Action", styles["small_center"]),
                _paragraph("Control", styles["small_center"]),
                _paragraph("Instructions", styles["small_center"]),
            ]
        ]
        recommendation_data.extend(
            [
                _paragraph(f"{item.title} ({item.step_id})", styles["small"]),
                _paragraph(
                    f"{_human(item.step_type)} / {_human(item.risk_level)} risk / "
                    + ("Approval required" if item.requires_human_approval else "Pre-approved"),
                    styles["small"],
                ),
                _paragraph(item.instructions, styles["small"]),
            ]
            for item in recommendations
        )
        story.append(
            _table(
                recommendation_data,
                [43 * mm, 36 * mm, 81 * mm],
                header=True,
                repeat_rows=1,
            )
        )
    else:
        story.append(
            _paragraph(
                "No catalogue recommendations are attached to the top hypothesis.", styles["body"]
            )
        )

    story.append(_paragraph("Audit Trail", styles["heading"]))
    audit_data = [
        [
            _paragraph("Timestamp", styles["small_center"]),
            _paragraph("Actor", styles["small_center"]),
            _paragraph("Action", styles["small_center"]),
            _paragraph("Object", styles["small_center"]),
        ]
    ]
    audit_data.extend(
        [
            _paragraph(_iso(record.timestamp), styles["small"]),
            _paragraph(f"{record.actor_type.value}:{record.actor_id or 'system'}", styles["small"]),
            _paragraph(record.action, styles["small"]),
            _paragraph(f"{record.object_type}:{record.object_id}", styles["small"]),
        ]
        for record in audits
    )
    if len(audit_data) == 1:
        audit_data.append(
            [_paragraph("-", styles["small"])] * 2
            + [
                _paragraph("No audit records available", styles["small"]),
                _paragraph("-", styles["small"]),
            ]
        )
    story.append(
        _table(audit_data, [33 * mm, 31 * mm, 47 * mm, 49 * mm], header=True, repeat_rows=1)
    )
    story.extend(
        [
            Spacer(1, 4 * mm),
            _paragraph(
                f"Explanation generator: {snapshot.explanation.generator}. Recommendations are advisory and are not automatically executed.",
                styles["subtitle"],
            ),
        ]
    )

    def draw_page(canvas, doc):
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(15 * mm, height - 12 * mm, width - 15 * mm, height - 12 * mm)
        canvas.setFillColor(CYAN)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.drawString(15 * mm, height - 9 * mm, "NETWORK OPERATIONS / SHIFT HANDOVER")
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(15 * mm, 9 * mm, _ascii(snapshot.incident.incident_id))
        canvas.drawRightString(width - 15 * mm, 9 * mm, f"Page {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=draw_page, onLaterPages=draw_page)
    return buffer.getvalue()

# Shift-Handover Report Extension

**Status:** Implemented and verified on 2026-07-16  
**Relationship to the blueprint:** Additive, post-blueprint extension

## Why this document exists

The original [`BLUEPRINT.md`](../BLUEPRINT.md) requires the incident
investigation, evidence, recommendations, reviews, and append-only audit trail.
It does not require an operator-facing handover document or downloadable
Markdown/PDF reports.

The export capability was added later to strengthen the prototype
demonstration. It converts the already-published investigation state into a
clean document suitable for shift handover notes or adaptation into a client
RCA email. This document records that additional scope without changing the
original blueprint.

## Operator experience

The incident header provides two one-click exports:

- **Markdown** for pasting into handover documents, tickets, chat, or email;
- **PDF handover** for a stable, presentation-ready attachment.

Both downloads use a timestamped filename containing the incident ID:

```text
incident-<incident-id>-shift-handover-<UTC-timestamp>.md
incident-<incident-id>-shift-handover-<UTC-timestamp>.pdf
```

## Report contents

Each format contains:

1. incident title, status, severity, time window, and affected entities;
2. the validated explanation summary;
3. the top-ranked hypothesis, score, and evidence coverage;
4. observed, correlated, conflicting, and missing evidence;
5. a chronological timeline of attached incident events, with excluded
   contextual events counted separately;
6. operator review actions already recorded for the analysis run;
7. catalogue-backed recommended next actions, clearly marked as advisory; and
8. the complete incident audit trail in chronological order.

## Snapshot and safety contract

Reports are generated from the same immutable `InvestigationResponse` used by
the incident UI. All run-scoped data must match the incident's current
analysis-run pointer before export. Recommendations remain suggestions and are
never executed by report generation.

The audit export reads every append-only incident audit page and sorts records
by `(timestamp, audit_id)`. The renderer does not query raw reference datasets,
re-run detection, invoke Ollama, change hypothesis rankings, or mutate incident
state.

## API extension

Two generated-contract endpoints were added:

| Endpoint | Media type | Purpose |
|---|---|---|
| `GET /api/v1/incidents/{incident_id}/handover.md` | `text/markdown` | Download editable handover text |
| `GET /api/v1/incidents/{incident_id}/handover.pdf` | `application/pdf` | Download the formatted PDF |

Responses include `Content-Disposition` with the generated filename and
`X-Analysis-Run-ID` with the snapshot identity. Both headers are exposed
through CORS for browser downloads.

## PDF implementation

PDF output uses pinned `reportlab==5.0.0`. The document is A4 and includes
consistent section hierarchy, evidence and timeline tables, recommendation and
audit tables, page headers, incident footers, and page numbering. Text is
normalised to PDF-safe ASCII punctuation so local generation does not depend
on external fonts or network access.

## Verification record

The implementation is covered by:

- renderer tests for required Markdown sections, audit ordering, stable
  timestamped filenames, and valid non-empty ReportLab PDF bytes;
- a production replay integration test covering both HTTP download endpoints;
- frontend tests covering both one-click browser downloads;
- generated OpenAPI and TypeScript freshness checks; and
- a render-to-PNG visual inspection of every PDF page for alignment,
  legibility, clipping, and overlap.

At implementation completion, the full suites reported **285 backend tests**
and **30 frontend tests** passing, with the production frontend build and
generated-contract checks also passing.

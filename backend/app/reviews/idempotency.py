from __future__ import annotations

import hashlib


def review_request_id(incident_id: str, client_action_id: str) -> str:
    """Stable mutation identity shared by the Phase-3 service and API shell."""

    digest = hashlib.sha256(f"{incident_id}|{client_action_id}".encode()).hexdigest()
    return f"req_review_{digest[:20]}"

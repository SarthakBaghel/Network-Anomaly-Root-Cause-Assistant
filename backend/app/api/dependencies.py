"""Shared FastAPI dependencies.

The session dependency is re-exported rather than reimplemented so tests and
all routers override the same callable identity.
"""

from app.db.session import get_session

__all__ = ["get_session"]

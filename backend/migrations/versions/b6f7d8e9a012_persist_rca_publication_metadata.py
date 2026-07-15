"""persist immutable RCA publication metadata

Revision ID: b6f7d8e9a012
Revises: a3f1c9d7e452
Create Date: 2026-07-15 21:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6f7d8e9a012"
down_revision: Union[str, None] = "a3f1c9d7e452"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column(
            "topology_states",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "typed_paths",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "conflict_reason_codes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    op.add_column(
        "analysis_runs",
        sa.Column(
            "evidence_requirements",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "evidence_requirements")
    op.drop_column("analysis_runs", "conflict_reason_codes")
    op.drop_column("analysis_runs", "typed_paths")
    op.drop_column("analysis_runs", "topology_states")

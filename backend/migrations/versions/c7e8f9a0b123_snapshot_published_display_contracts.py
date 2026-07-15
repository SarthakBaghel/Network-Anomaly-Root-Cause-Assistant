"""snapshot published topology and recommendation display contracts

Revision ID: c7e8f9a0b123
Revises: b6f7d8e9a012
Create Date: 2026-07-15 23:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7e8f9a0b123"
down_revision: Union[str, None] = "b6f7d8e9a012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column(
            "topology_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "playbook_recommendations",
        sa.Column(
            "presentation",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("playbook_recommendations", "presentation")
    op.drop_column("analysis_runs", "topology_snapshot")

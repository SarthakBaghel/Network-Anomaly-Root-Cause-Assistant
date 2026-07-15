"""add_ewma_baselines_table

Revision ID: a3f1c9d7e452
Revises: 2eff20be3718
Create Date: 2026-07-15 10:40:00.000000

Adds the ewma_baselines table for persisting per-(entity_id, signal_name)
EWMA state across application restarts. This allows the EwmaDetector to
continue from its last known baseline rather than cold-starting on boot.

BLUEPRINT §3.2: EWMA alpha is NOT stored in this table — it is a fixed
config constant in ewma_detector.py. This table stores only the running
mean, variance, sample count, and last-updated timestamp.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f1c9d7e452'
down_revision: Union[str, None] = '2eff20be3718'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ewma_baselines',
        sa.Column('entity_id', sa.String(), nullable=False),
        sa.Column('signal_name', sa.String(), nullable=False),
        sa.Column('ewma_mean', sa.Float(), nullable=False),
        sa.Column('ewma_variance', sa.Float(), nullable=False),
        sa.Column('n_samples', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('entity_id', 'signal_name'),
    )
    op.create_index(
        'ix_ewma_entity_signal',
        'ewma_baselines',
        ['entity_id', 'signal_name'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_ewma_entity_signal', table_name='ewma_baselines')
    op.drop_table('ewma_baselines')

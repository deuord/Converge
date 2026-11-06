"""add session title

Revision ID: efcd976f1f26
Revises: 17244a7c752a
Create Date: 2026-11-06 14:47:18.994434

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'efcd976f1f26'
down_revision: str | Sequence[str] | None = '17244a7c752a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """会话标题:首轮用户消息截断生成,列表展示用(见 plan §1.7)"""
    op.add_column(
        'session',
        sa.Column('title', sa.String(length=64), nullable=True,
                  comment='会话标题,首轮用户消息截断生成;NULL=尚未生成'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('session', 'title')

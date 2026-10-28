"""init singular table names

Revision ID: 17244a7c752a
Revises: 
Create Date: 2026-10-27 17:50:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '17244a7c752a'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # session(先建,message 有外键依赖它)
    op.create_table(
        'session',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('session_id', sa.String(length=24), nullable=False, unique=True),
        sa.Column('pending', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('model', sa.String(length=64), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='创建时间,UTC'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, comment='更新时间,UTC'),
        sa.Column('created_user_nickname', sa.String(length=64), nullable=True, comment='创建用户昵称,用于审计/分析'),
        sa.Column('updated_user_nickname', sa.String(length=64), nullable=True, comment='更新用户昵称,用于审计/分析'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='软删除时间,UTC;NULL=存活,非 NULL=已删除'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("ALTER TABLE session ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE session ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY")

    # message(依赖 session 的外键)
    op.create_table(
        'message',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('session_id', sa.String(length=24), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('tool_calls', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('tool_call_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='创建时间,UTC'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, comment='更新时间,UTC'),
        sa.Column('created_user_nickname', sa.String(length=64), nullable=True, comment='创建用户昵称,用于审计/分析'),
        sa.Column('updated_user_nickname', sa.String(length=64), nullable=True, comment='更新用户昵称,用于审计/分析'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='软删除时间,UTC;NULL=存活,非 NULL=已删除'),
        sa.ForeignKeyConstraint(['session_id'], ['session.session_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'seq', name='uq_message_session_seq'),
    )
    op.execute("ALTER TABLE message ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE message ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY")
    op.create_index('idx_message_session_seq', 'message', ['session_id', 'seq'], unique=False)

    # recent_file(无外键依赖)
    op.create_table(
        'recent_file',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('op', sa.String(length=16), nullable=False),
        sa.Column('accessed_at', sa.DateTime(timezone=True), nullable=False, comment='访问发生时间,UTC'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, comment='创建时间,UTC'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, comment='更新时间,UTC'),
        sa.Column('created_user_nickname', sa.String(length=64), nullable=True, comment='创建用户昵称,用于审计/分析'),
        sa.Column('updated_user_nickname', sa.String(length=64), nullable=True, comment='更新用户昵称,用于审计/分析'),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='软删除时间,UTC;NULL=存活,非 NULL=已删除'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("ALTER TABLE recent_file ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE recent_file ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY")
    op.create_index(
        'idx_recent_file_accessed', 'recent_file', ['accessed_at'],
        unique=False, postgresql_using='btree',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_message_session_seq', table_name='message')
    op.drop_table('message')
    op.drop_table('session')
    op.drop_index('idx_recent_file_accessed', table_name='recent_file', postgresql_using='btree')
    op.drop_table('recent_file')

# store/model.py — ORM 模型层:定义数据库"长什么样",不写任何读写逻辑
#
# 对应 Go 里的:struct + db tag
# 差异:Go 把结构体和增删改查放一起;Python 刻意拆开——
#   本文件只说"表结构",读写逻辑放 store/session_store.py 等 Repository 类
#
# Alembic autogenerate 的真相来源:
#   1. 本文件所有 Base 子类 → Base.metadata 持有完整表结构
#   2. migrations/env.py 把 target_metadata = Base.metadata
#   3. 跑 alembic revision --autogenerate 时,Alembic 对比 metadata 和 DB 里现有表
#      → 生成一份带 upgrade()/downgrade() 的迁移脚本(和 Goose 的 .sql 完全对等)
#
# 所有业务表统一三件套(公司规范):created_at / updated_at / deleted
#   TimestampMixin 抽出来,所有表继承,一张都不能漏

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# Base:所有 ORM 模型的父类。Base.metadata 是"数据库全貌",Alembic 对比差异靠它
# 对应 Go 里 GORM 的 gorm.Model,但更轻——不会自动加 Id/CreatedAt/UpdatedAt
class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    """UTC 当前时间(带时区)。default/onupdate 需要可调用对象,统一用它
    不用 datetime.utcnow():返回 naive 时间,官方已不推荐(ruff DTZ003)"""
    return datetime.now(UTC)


class TimestampMixin:
    """所有业务表统一五件套:created_at / updated_at / created_user_nickname / updated_user_nickname / deleted_at

    公司规范,一张业务表都不能漏。
    对应 Go 里 GORM 的 gorm.Model + 审计字段 + gorm.DeletedAt

    deleted_at vs deleted(0/1):选 deleted_at,因为能审计"什么时候删的"
    软删查询统一 WHERE deleted_at IS NULL;定时任务扫 deleted_at < now() - 30 天硬删
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        comment="创建时间,UTC"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=_utcnow, onupdate=_utcnow,
        comment="更新时间,UTC"
    )
    # 审计:哪个用户创建/更新的。nullable=True 因为桌面助手单用户暂时用不到,
    # 但公司规范必须留着——后期多用户/服务端部署时填,不做 NOT NULL 强迫自己
    created_user_nickname: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="创建用户昵称,用于审计/分析"
    )
    updated_user_nickname: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
        comment="更新用户昵称,用于审计/分析"
    )
    # 软删除:NULL = 存活;非 NULL = 已删除(存删除时刻 UTC)
    # 选 deleted_at(有时间戳)而非 deleted 0/1:公司规范;代价是查询要写 IS NULL 而非 = 0
    # 定时任务扫 deleted_at < now() - 30 天硬删(级联删除子表)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="软删除时间,UTC;NULL=存活,非 NULL=已删除"
    )


class Session(Base, TimestampMixin):
    """会话表:一个 Session = 一串消息 + 可能的断点

    为什么 messages 不在这表里?见 messages 表注释 + plan §2.4:
      - 上生产的对话产品全是独立消息表,支持分页/编辑/搜索
      - pending 是回合级断点,一个会话同时只有一份,整存整取,留这里合理

    对应 Go:
      type Session struct {
          ID        int64  `gorm:"primaryKey"`          // 技术主键,公司规范所有表必有
          SessionID string `gorm:"unique;size:24"`      // 业务键,应用侧生成,暴露给前端
          Pending   string `gorm:"type:jsonb"`
          Model     string `gorm:"size:64"`
          ...
          gorm.Model
          DeletedAt gorm.DeletedAt
      }
    """
    __tablename__ = "session"

    # id:技术主键,公司规范所有业务表必有。BIGINT GENERATED ALWAYS AS IDENTITY
    id: Mapped[int] = mapped_column(primary_key=True)

    # session_id = 应用侧生成的 uuid4().hex[:12],业务唯一键,暴露给前端/日志/API
    # 不用做主键是因为:所有表 id 字段统一做技术主键,业务键独立为 UNIQUE
    session_id: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)

    # pending:回合断点(用户需要确认才能续跑的场景)。None = 无断点
    # nullable=True 允许空 JSONB
    pending: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # 会话级模型切换:null 表示走 config/models.yaml 的默认
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # TTL:expires_at 到了就认为会话过期。惰性清理(查的时候顺手过滤,不搞定时任务)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Message(Base, TimestampMixin):
    """消息表:一列一条 LLM 消息(user / assistant / tool)

    为什么独立表而不是 JSONB 整存:
      - 上生产的对话产品(元宝 / DeepSeek App / ChatGPT)全是独立消息表
      - 支持分页加载、单条编辑、跨会话搜索、消息级埋点统计
      - seq 列保证排序,比自增 id 更可靠(删除/补录时 id 不连续)
      - assistant 带 tool_calls 时,content 可能为空,tool_calls JSONB 存调用列表
      - role=tool 时,tool_call_id 指向对应的 tool_call.id,成对关联

    对应 Go:
      type Message struct {
          ID         int64     `gorm:"primaryKey"`
          SessionID  string    `gorm:"size:24;index"`
          Role       string    `gorm:"size:16;not null"`
          Content    string
          Seq        int       `gorm:"not null"`
          ToolCalls  string    `gorm:"type:jsonb"`
          ToolCallID string    `gorm:"size:64"`
          ...
          gorm.Model
          IsDeleted int `gorm:"default:0"`
      }
    """
    __tablename__ = "message"

    # PostgreSQL 的 id 列推荐用 GENERATED ALWAYS AS IDENTITY
    # SQLAlchemy 2.0 语法: autoincrement 留空就行,PG 会自动生成
    id: Mapped[int] = mapped_column(primary_key=True)

    # session_id 外键,级联硬删:session 被定时任务硬删时 message 自动全删
    # session 软删(deleted_at IS NOT NULL)时 message 还在,但查询 session 时已过滤,前端自然看不到
    session_id: Mapped[str] = mapped_column(
        String(24), ForeignKey("session.session_id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # role 取值: system / user / assistant / tool
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    # content:消息正文。assistant 有 tool_calls 时 content 可能为空字符串
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    # seq:会话内序号,从 0 或 1 开始连续递增
    # LLM 拼 prompt 时 ORDER BY seq,比 ORDER BY id 可靠(删除/补录时 id 不连续)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    # tool_calls:assistant 的工具调用列表,v2 起有值
    # 结构:[{"id":"call_xxx","type":"function","function":{"name":"run_command","arguments":"..."}}]
    tool_calls: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # tool_call_id:role=tool 时指向对应的 tool_call.id,成对关联
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 同一会话内 seq 必须唯一,防止并发写入时序号冲突
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_messages_session_seq"),
        Index("idx_messages_session_seq", "session_id", "seq"),
    )


class RecentFile(Base, TimestampMixin):
    """最近访问记录:read/write/edit 成功时记一条

    对应 Go:
      type RecentFile struct {
          ID        int64     `gorm:"primaryKey"`
          Path      string    `gorm:"size:1024;not null"`
          Op        string    `gorm:"size:16;not null"`   // read / write / edit
          AccessedAt time.Time `gorm:"index"`
          ...
          gorm.Model
          IsDeleted int `gorm:"default:0"`
      }
    """
    __tablename__ = "recent_file"

    # PostgreSQL 的 id 列推荐用 GENERATED ALWAYS AS IDENTITY
    # SQLAlchemy 2.0 语法: autoincrement 留空就行,PG 会自动生成
    id: Mapped[int] = mapped_column(primary_key=True)

    # path 可能很长(用户项目深层目录),Text 比 String(255)稳
    path: Mapped[str] = mapped_column(Text, nullable=False)

    # op 取值只有 read/write/edit 三种,够用了;不做 enum,简单字符串
    op: Mapped[str] = mapped_column(String(16), nullable=False)

    # 倒序查最近访问时走这个索引,比全表扫描快得多
    # 注意:accessed_at 是业务时间(访问发生的时间),不是 created_at(记录创建时间)
    # 两者语义相同,这里保留 accessed_at 名字是因为工具签名 list_recent_files 用的就是这个概念
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow,
        comment="访问发生时间,UTC"
    )

    __table_args__ = (
        Index("idx_recent_files_accessed", "accessed_at", postgresql_using="btree"),
    )

from datetime import datetime
from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
from src.utils.time import now

class LinkRegistry(Base):
    """每个数据批次一行：单调递增的同票关系版本号，兼作登记、撤销与快照的串行化锁点。"""
    __tablename__ = 'link_registries'

    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), primary_key=True)
    version: Mapped[int] = mapped_column(default=0)

class TicketLink(Base):
    """同一原票的两件扫描件之间的关系记录；撤销只标记不删除，留痕可查。"""
    __tablename__ = 'ticket_links'
    __table_args__ = (UniqueConstraint('dataset_id', 'left_id', 'right_id'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'), index=True)
    left_id: Mapped[str] = mapped_column(String(300))
    right_id: Mapped[str] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=now)
    revoked_by: Mapped[str | None] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None]

class RunLinkSnapshot(Base):
    """运行发起时固定的同票关系版本与快照，重试与导出都以它为准，创建后不再更改。"""
    __tablename__ = 'run_link_snapshots'

    run_id: Mapped[int] = mapped_column(ForeignKey('runs.id'), primary_key=True)
    version: Mapped[int]
    links: Mapped[list] = mapped_column(JSON)

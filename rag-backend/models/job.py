import uuid
from sqlalchemy import Column, Text, Integer, ForeignKey, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from core.database import Base
from core.enums import JobStatus, LogLevel


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default=JobStatus.QUEUED.value)
    payload = Column(JSONB, nullable=False, default=dict)
    total = Column(Integer, nullable=False, default=0)
    processed = Column(Integer, nullable=False, default=0)
    added = Column(Integer, nullable=False, default=0)
    updated = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    errors = Column(Integer, nullable=False, default=0)
    error = Column(Text)
    result = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan",
                        order_by="JobLog.created_at")


class JobLog(Base):
    __tablename__ = "job_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("ingestion_jobs.id", ondelete="CASCADE"), nullable=False)
    level = Column(Text, nullable=False, default=LogLevel.INFO.value)
    message = Column(Text, nullable=False)
    file = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job = relationship("IngestionJob", back_populates="logs")

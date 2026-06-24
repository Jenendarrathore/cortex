# NOTE: DDL + indexes (and chunks.fts) are owned by db/schema.sql, not by these
# models. Keep columns here in sync with that file; it is the source of truth.
import uuid
from sqlalchemy import Column, Text, Integer, Date, ARRAY, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from core.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_path = Column(Text, unique=True, nullable=False)
    file_hash = Column(Text, nullable=False)
    title = Column(Text)
    author = Column(Text)
    source_url = Column(Text)
    category = Column(Text)
    tags = Column(ARRAY(Text), default=list)
    doc_date = Column(Date)
    raw_content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    chunks = relationship("Chunk", back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    content = Column(Text, nullable=False)
    embedding = Column(Vector(768))
    chunk_index = Column(Integer, nullable=False)
    heading = Column(Text)
    token_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="chunks")

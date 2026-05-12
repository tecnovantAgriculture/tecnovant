from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class StorageLocation(str, Enum):
    S3 = "s3"
    LOCAL = "local"


class AssetType(str, Enum):
    GEOTIFF = "geotiff"
    IMAGE = "image"


class Asset(db.Model):
    __tablename__ = "media_asset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ext: Mapped[str] = mapped_column(String(16), nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    storage: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    is_geo: Mapped[bool] = mapped_column(Boolean, default=False)
    crs: Mapped[Optional[str]] = mapped_column(String(128))
    bounds: Mapped[Optional[dict]] = mapped_column(JSON)
    transform: Mapped[Optional[dict]] = mapped_column(JSON)
    mpp: Mapped[Optional[float]] = mapped_column(Float)
    exif: Mapped[Optional[dict]] = mapped_column(JSON)
    variants = relationship("AssetVariant", cascade="all, delete-orphan")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (UniqueConstraint("sha256", "size_bytes", name="uq_asset_dedup"),)


class AssetVariant(db.Model):
    __tablename__ = "media_variant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_asset.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # "thumbnail", "tile", "cog"
    storage: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(String(1024))
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)

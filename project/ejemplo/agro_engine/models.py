"""Consolidated models from agrovista and media modules."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    JSON,
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


# ==================== Media Models ====================

class StorageLocation(str, Enum):
    S3 = "s3"
    LOCAL = "local"


class AssetType(str, Enum):
    GEOTIFF = "geotiff"
    IMAGE = "image"


class Asset(db.Model):
    """Media asset model for file management."""
    __tablename__ = "media_asset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ext: Mapped[str] = mapped_column(String(16), nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    storage: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    is_geo: Mapped[bool] = mapped_column(Boolean, default=False)
    crs: Mapped[Optional[str]] = mapped_column(String(128))
    bounds: Mapped[Optional[dict]] = mapped_column(JSON)
    transform: Mapped[Optional[dict]] = mapped_column(JSON)
    mpp: Mapped[Optional[float]] = mapped_column(Float)
    exif: Mapped[Optional[dict]] = mapped_column(JSON)
    variants = relationship("AssetVariant", cascade="all, delete-orphan")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("sha256", "size_bytes", name="uq_asset_dedup"),)


class AssetVariant(db.Model):
    """Media asset variant (thumbnails, etc.)."""
    __tablename__ = "media_variant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("media_asset.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    storage: Mapped[str] = mapped_column(String(16))
    storage_key: Mapped[str] = mapped_column(String(1024))
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)


# ==================== Agrovista Models (Priority) ====================

class NDVIImage(db.Model):
    """Modelo para almacenar metadatos de imágenes NDVI procesadas."""
    __tablename__ = "ndvi_images"

    id = db.Column(db.String(32), primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    png_path = db.Column(db.String(300), nullable=False)
    npy_path = db.Column(db.String(300), nullable=False)
    width = db.Column(db.Integer, nullable=False)
    height = db.Column(db.Integer, nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<NDVIImage {self.id}>"


class AnalysisCrop(db.Model):
    """Cultivo de referencia utilizado para análisis de Agrovista."""
    __tablename__ = "analysis_crops"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    secondary_objectives = db.relationship(
        "SecondaryObjective",
        back_populates="analysis_crop",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<AnalysisCrop {self.name}>"


class SecondaryObjective(db.Model):
    """Objetivos secundarios generados desde análisis NDVI."""
    __tablename__ = "secondary_objectives"

    id = db.Column(db.Integer, primary_key=True)
    analysis_crop_id = db.Column(
        db.Integer,
        db.ForeignKey("analysis_crops.id"),
        nullable=False,
    )
    protein_average = db.Column(db.Float, nullable=False)
    nitrogen_estimated = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analysis_crop = db.relationship(
        "AnalysisCrop",
        back_populates="secondary_objectives",
    )
    nutrient_targets = db.relationship(
        "SecondaryObjectiveNutrient",
        back_populates="secondary_objective",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<SecondaryObjective {self.id} crop={self.analysis_crop_id}>"


class SecondaryObjectiveNutrient(db.Model):
    """Valores objetivo por nutriente para un objetivo secundario."""
    __tablename__ = "secondary_objective_nutrients"

    id = db.Column(db.Integer, primary_key=True)
    secondary_objective_id = db.Column(
        db.Integer,
        db.ForeignKey("secondary_objectives.id"),
        nullable=False,
    )
    nutrient_id = db.Column(
        db.Integer,
        db.ForeignKey("nutrients.id"),
        nullable=False,
    )
    target_value = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    secondary_objective = db.relationship(
        "SecondaryObjective",
        back_populates="nutrient_targets",
    )
    nutrient = db.relationship("Nutrient")

    __table_args__ = (
        db.UniqueConstraint(
            "secondary_objective_id",
            "nutrient_id",
            name="uq_secondary_objective_nutrient",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SecondaryObjectiveNutrient objective={self.secondary_objective_id} "
            f"nutrient={self.nutrient_id}>"
        )


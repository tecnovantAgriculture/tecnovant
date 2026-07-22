from __future__ import annotations

import secrets
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class OrthophotoMission(db.Model):
    __tablename__ = "orthophoto_mission"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    farm_id: Mapped[int | None] = mapped_column(
        ForeignKey("farms.id", ondelete="SET NULL"), index=True
    )
    lot_id: Mapped[int | None] = mapped_column(
        ForeignKey("lots.id", ondelete="SET NULL"), index=True
    )
    upload_token: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True, default=lambda: secrets.token_urlsafe(32)
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="receiving")
    processing_job_id: Mapped[str | None] = mapped_column(String(64))
    processing_error: Mapped[str | None] = mapped_column(Text)
    webodm_project_id: Mapped[int | None] = mapped_column(Integer)
    webodm_task_id: Mapped[str | None] = mapped_column(String(64))
    progress: Mapped[float | None] = mapped_column(Float)
    available_assets: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    photos = relationship(
        "OrthophotoPhoto", back_populates="mission", cascade="all, delete-orphan"
    )
    organization = relationship("Organization")
    farm = relationship("Farm")
    lot = relationship("Lot")

    @property
    def folder_path(self) -> str | None:
        if not self.organization or not self.farm or not self.lot:
            return None
        return f"{self.organization.name} / {self.farm.name} / {self.lot.name} / {self.name}"


class OrthophotoPhoto(db.Model):
    __tablename__ = "orthophoto_photo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("orthophoto_mission.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_asset.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    mission = relationship("OrthophotoMission", back_populates="photos")
    asset = relationship("Asset")

from datetime import datetime

from app.extensions import db


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

    def __repr__(self) -> str:  # pragma: no cover - simple representation
        return f"<NDVIImage {self.id}>"


class AnalysisCrop(db.Model):
    """Cultivo de referencia utilizado para análisis de Agrovista."""

    __tablename__ = "analysis_crops"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    secondary_objectives = db.relationship(
        "SecondaryObjective",
        back_populates="analysis_crop",
        lazy="dynamic",
    )

    def __repr__(self) -> str:  # pragma: no cover - simple representation
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
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

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

    def __repr__(self) -> str:  # pragma: no cover - simple representation
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
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

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

    def __repr__(self) -> str:  # pragma: no cover - simple representation
        return (
            f"<SecondaryObjectiveNutrient objective={self.secondary_objective_id} "
            f"nutrient={self.nutrient_id}>"
        )

from datetime import date, datetime, timedelta
from enum import Enum

from marshmallow import Schema, ValidationError, fields, validates

from app.core.models import User
from app.extensions import cache, db

leaf_analysis_nutrients = db.Table(
    "leaf_analysis_nutrients",
    db.Column(
        "leaf_analysis_id",
        db.Integer,
        db.ForeignKey("leaf_analyses.id"),
        primary_key=True,
    ),
    db.Column(
        "nutrient_id", db.Integer, db.ForeignKey("nutrients.id"), primary_key=True
    ),
    db.Column("value", db.Float, nullable=False),
    db.Column("created_at", db.DateTime, default=datetime.utcnow),
)

nutrient_application_nutrients = db.Table(
    "nutrient_application_nutrients",
    db.Column(
        "nutrient_application_id",
        db.Integer,
        db.ForeignKey("nutrient_applications.id"),
        primary_key=True,
    ),
    db.Column(
        "nutrient_id", db.Integer, db.ForeignKey("nutrients.id"), primary_key=True
    ),
    db.Column("quantity", db.Float, nullable=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow),
)

objective_nutrients = db.Table(
    "objective_nutrients",
    db.Column(
        "objective_id", db.Integer, db.ForeignKey("objectives.id"), primary_key=True
    ),
    db.Column(
        "nutrient_id", db.Integer, db.ForeignKey("nutrients.id"), primary_key=True
    ),
    db.Column("target_value", db.Float, nullable=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow),
)

product_contribution_nutrients = db.Table(
    "product_contribution_nutrients",
    db.Column(
        "product_contribution_id",
        db.Integer,
        db.ForeignKey("product_contributions.id"),
        primary_key=True,
    ),
    db.Column(
        "nutrient_id", db.Integer, db.ForeignKey("nutrients.id"), primary_key=True
    ),
    db.Column("contribution", db.Float, nullable=True),
    db.Column("created_at", db.DateTime, default=datetime.utcnow),
)


class NutrientCategory(Enum):
    MACRONUTRIENT = "Macronutrient"
    MICRONUTRIENT = "Micronutrient"


class Farm(db.Model):
    """Modelo que representa una granja"""

    __tablename__ = "farms"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    organization = db.relationship("Organization", backref="farms")
    lots = db.relationship("Lot", back_populates="farm", lazy="dynamic")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    __table_args__ = (
        db.Index("ix_farms_org_id", "org_id"),
        db.Index("ix_farms_org_id_name", "org_id", "name"),
    )

    def __repr__(self):
        return f"<Farm {self.name}>"


class Lot(db.Model):
    """Model representing a lot in a farm"""

    __tablename__ = "lots"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    area = db.Column(db.Float, nullable=False)
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    farm = db.relationship("Farm", back_populates="lots")
    lot_crops = db.relationship("LotCrop", back_populates="lot", lazy="dynamic")
    common_analyses = db.relationship(
        "CommonAnalysis", back_populates="lot", lazy="dynamic"
    )
    nutrient_applications = db.relationship(
        "NutrientApplication", back_populates="lot", lazy="dynamic"
    )
    productions = db.relationship("Production", back_populates="lot", lazy="dynamic")
    recommendations = db.relationship(
        "Recommendation", back_populates="lot", lazy="dynamic"
    )
    __table_args__ = (
        db.Index("ix_lots_farm_id", "farm_id"),
        db.Index("ix_lots_area", "area"),
    )

    def __repr__(self):
        return f"<Lot {self.name}>"

    @property
    def organization(self):
        return self.farm.organization if self.farm else None


class Crop(db.Model):
    """Model representing a crop"""

    # cultivos
    __tablename__ = "crops"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    lot_crops = db.relationship("LotCrop", back_populates="crop", lazy="dynamic")
    objectives = db.relationship("Objective", back_populates="crop", lazy="dynamic")

    def __repr__(self):
        return f"<Crop {self.name}>"


class LotCrop(db.Model):
    """Model representing the relationship between a lot and a crop"""

    __tablename__ = "lot_crops"
    id = db.Column(db.Integer, primary_key=True)
    lot_id = db.Column(db.Integer, db.ForeignKey("lots.id"), nullable=False)
    crop_id = db.Column(db.Integer, db.ForeignKey("crops.id"), nullable=False)
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    end_date = db.Column(db.Date, default=lambda: date.today() + timedelta(days=365))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    lot = db.relationship("Lot", back_populates="lot_crops")
    crop = db.relationship("Crop", back_populates="lot_crops")
    __table_args__ = (
        db.Index("ix_lot_crops_lot_id", "lot_id"),
        db.Index("ix_lot_crops_start_date", "start_date"),
    )

    def __repr__(self):
        return f"<LotCrop {self.id}>"

    @property
    def organization(self):
        return self.lot.organization if self.lot else None


class CommonAnalysis(db.Model):
    """Model representing a common analysis"""

    __tablename__ = "common_analyses"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    lot_id = db.Column(db.Integer, db.ForeignKey("lots.id"), nullable=False)
    protein = db.Column(db.Float)
    rest = db.Column(db.Float)
    rest_days = db.Column(db.Integer)
    energy = db.Column(db.Float)
    yield_estimate = db.Column(db.Float)  # for aforo
    month = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    lot = db.relationship("Lot", back_populates="common_analyses")
    soil_analysis = db.relationship(
        "SoilAnalysis", uselist=False, back_populates="common_analysis"
    )
    leaf_analysis = db.relationship(
        "LeafAnalysis", uselist=False, back_populates="common_analysis"
    )
    __table_args__ = (
        db.Index("ix_common_analyses_lot_id", "lot_id"),
        db.Index("ix_common_analyses_date", "date"),
    )

    def __repr__(self):
        return f"<CommonAnalysis {self.id}>"

    @property
    def organization(self):
        return self.lot.farm.organization if self.lot and self.lot.farm else None

    @property
    def farm_name(self):
        return self.lot.farm.name

    @property
    def lot_name(self):
        return self.lot.name


class SoilAnalysis(db.Model):
    """Model representing a soil analysis"""

    __tablename__ = "soil_analyses"
    id = db.Column(db.Integer, primary_key=True)
    common_analysis_id = db.Column(
        db.Integer, db.ForeignKey("common_analyses.id"), nullable=False
    )
    energy = db.Column(db.Float)
    grazing = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    common_analysis = db.relationship("CommonAnalysis", back_populates="soil_analysis")

    def __repr__(self):
        return f"<SoilAnalysis {self.id}>"


class Nutrient(db.Model):
    """Model representing a nutrient"""

    __tablename__ = "nutrients"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    symbol = db.Column(db.String(10), nullable=False, unique=True)
    unit = db.Column(db.String(20), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.Enum(NutrientCategory))
    cv = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    leaf_analyses = db.relationship(
        "LeafAnalysis", secondary=leaf_analysis_nutrients, back_populates="nutrients"
    )

    applications = db.relationship(
        "NutrientApplication",
        secondary=nutrient_application_nutrients,
        back_populates="nutrients",
    )

    objectives = db.relationship(
        "Objective", secondary=objective_nutrients, back_populates="nutrients"
    )

    product_contributions = db.relationship(
        "ProductContribution",
        secondary=product_contribution_nutrients,
        back_populates="nutrients",
    )

    def __repr__(self):
        return f"<Nutrient {self.name} ({self.symbol})>"


class LeafAnalysis(db.Model):
    """Model representing a leaf analysis"""

    __tablename__ = "leaf_analyses"
    id = db.Column(db.Integer, primary_key=True)
    common_analysis_id = db.Column(
        db.Integer, db.ForeignKey("common_analyses.id"), nullable=False
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    common_analysis = db.relationship("CommonAnalysis", back_populates="leaf_analysis")
    nutrients = db.relationship(
        "Nutrient", secondary=leaf_analysis_nutrients, back_populates="leaf_analyses"
    )

    def __repr__(self):
        return f"<LeafAnalysis {self.id}>"

    @property
    def organization(self):
        return self.common_analysis.organization if self.common_analysis else None

    @property
    def farm_name(self):
        return self.common_analysis.lot.farm.name if self.common_analysis else None

    @property
    def lot_name(self):
        return self.common_analysis.lot.name if self.common_analysis else None


class Recommendation(db.Model):
    """Model representing a recommendation for a lot"""

    __tablename__ = "recommendations"
    id = db.Column(db.Integer, primary_key=True)
    lot_id = db.Column(db.Integer, db.ForeignKey("lots.id"), nullable=False)
    crop_id = db.Column(db.Integer, db.ForeignKey("crops.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    author = db.Column(db.String(100))
    title = db.Column(db.String(255), nullable=False)
    limiting_nutrient_id = db.Column(db.String(255), nullable=False)
    automatic_recommendations = db.Column(
        db.Text
    )  # Recomendaciones automáticas (puede ser JSON)
    text_recommendations = db.Column(db.Text)  # Recomendaciones en texto libre
    optimal_comparison = db.Column(
        db.Text
    )  # Comparación con niveles óptimos (puede ser JSON)
    minimum_law_analyses = db.Column(db.Text)  # Análisis legal mínimo (puede ser JSON)
    soil_analysis_details = db.Column(
        db.Text
    )  # Detalles del análisis de suelo (puede ser JSON)
    foliar_analysis_details = db.Column(
        db.Text
    )  # Detalles del análisis foliar (puede ser JSON)
    applied = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relaciones
    lot = db.relationship("Lot", back_populates="recommendations")
    crop = db.relationship("Crop")

    __table_args__ = (
        db.Index("ix_recommendations_lot_id", "lot_id"),
        db.Index("ix_recommendations_date", "date"),
    )

    def __repr__(self):
        return f"<Recommendation {self.id}>"

    @property
    def organization(self):
        return self.lot.farm.organization if self.lot and self.lot.farm else None


class NutrientApplication(db.Model):
    """Model representing a nutrient application"""

    __tablename__ = "nutrient_applications"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey("lots.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    lot = db.relationship("Lot", back_populates="nutrient_applications")
    nutrients = db.relationship(
        "Nutrient",
        secondary=nutrient_application_nutrients,
        back_populates="applications",
    )

    def __repr__(self):
        return f"<NutrientApplication {self.id}>"

    @property
    def organization(self):
        return self.lot.farm.organization if self.lot and self.lot.farm else None


class Objective(db.Model):
    """Model representing nutrient objectives for a crop"""

    __tablename__ = "objectives"
    id = db.Column(db.Integer, primary_key=True)
    crop_id = db.Column(db.Integer, db.ForeignKey("crops.id"), nullable=False)
    target_value = db.Column(db.Float, nullable=False)
    protein = db.Column(db.Float)
    rest = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    crop = db.relationship("Crop", back_populates="objectives")
    nutrients = db.relationship(
        "Nutrient", secondary=objective_nutrients, back_populates="objectives"
    )

    def __repr__(self):
        return f"<Objective {self.id}>"


class Production(db.Model):
    """Model representing production from a lot"""

    __tablename__ = "productions"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    lot_id = db.Column(db.Integer, db.ForeignKey("lots.id"), nullable=False)
    area = db.Column(db.Float)
    production_kg = db.Column(db.Float)
    bags = db.Column(db.Integer)
    harvest = db.Column(db.String(100))
    month = db.Column(db.Integer)
    variety = db.Column(db.String(100))
    price_per_kg = db.Column(db.Float)
    protein_65dde = db.Column(db.Float)
    discount = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    lot = db.relationship("Lot", back_populates="productions")
    __table_args__ = (
        db.Index("ix_productions_lot_id", "lot_id"),
        db.Index("ix_productions_date", "date"),
    )

    def __repr__(self):
        return f"<Production {self.id}>"

    @property
    def organization(self):
        return self.lot.farm.organization if self.lot and self.lot.farm else None


class Product(db.Model):
    """Model representing a product"""

    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    product_contributions = db.relationship(
        "ProductContribution", back_populates="product", lazy="dynamic"
    )
    product_prices = db.relationship(
        "ProductPrice", back_populates="product", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Product {self.name}>"


class ProductContribution(db.Model):
    """Model representing nutrient contributions of a product"""

    __tablename__ = "product_contributions"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    product = db.relationship("Product", back_populates="product_contributions")
    nutrients = db.relationship(
        "Nutrient",
        secondary=product_contribution_nutrients,
        back_populates="product_contributions",
    )

    def __repr__(self):
        return f"<ProductContribution {self.id}>"


class ProductPrice(db.Model):
    """Model representing prices of a product"""

    __tablename__ = "product_prices"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    price = db.Column(db.Float, nullable=False)
    supplier = db.Column(db.String(100))
    start_date = db.Column(db.Date, nullable=False, default=date.today)
    end_date = db.Column(db.Date, default=lambda: date.today() + timedelta(days=365))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    product = db.relationship("Product", back_populates="product_prices")
    __table_args__ = (
        db.Index("ix_product_prices_product_id", "product_id"),
        db.Index("ix_product_prices_start_date", "start_date"),
    )

    def __repr__(self):
        return f"<ProductPrice {self.id}>"


# Validación de nutrientes
class NutrientValueSchema(Schema):
    value = fields.Float(required=True)

    @validates("value")
    def validate_value(self, value):
        if value < 0:
            raise ValidationError("El valor del nutriente no puede ser negativo.")


# Ejemplo de uso de validación
def validate_nutrient_value(value):
    schema = NutrientValueSchema()
    try:
        schema.load({"value": value})
    except ValidationError as err:
        raise ValueError(f"Valor del nutriente inválido: {err}")


# Ejemplo de uso con caching
@cache.cached(timeout=3600, key_prefix="view_%s" % __name__)
def get_all_users():
    return User.query.options(db.joinedload(User.farms)).all()


# Example query optimization using joinedload
# def get_lot_details(lot_id):
#     return Lot.query.options(
#         db.joinedload(Lot.farm),
#         db.joinedload(Lot.lot_crops),
#         db.joinedload(Lot.common_analyses),
#         db.joinedload(Lot.nutrient_applications),
#         db.joinedload(Lot.productions),
#         db.joinedload(Lot.recommendations),
#     ).get(lot_id)


# Example of using subqueryload for more complex relationships
def get_lot_with_crops(lot_id):
    return Lot.query.options(
        db.joinedload(Lot.farm), db.subqueryload(Lot.lot_crops).joinedload(LotCrop.crop)
    ).get(lot_id)

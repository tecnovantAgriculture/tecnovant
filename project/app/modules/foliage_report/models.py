"""Models for the foliage_report module.

Currently a single auxiliary table ``recommendation_doses`` that stores
per-product dose/cost rows for each generated Recommendation. The
combination may include several products (the optimizer returns a
Dict[product, cantidad]) and the UI needs to render each one with its
own unit and cost.

Isolation from ``foliage/models.py`` is intentional: keeping the
``Recommendation`` model untouched avoids touching the hotspot and
preserves the existing schema/migrations surface.
"""

from datetime import datetime

from app.extensions import db


class RecommendationDose(db.Model):
    """One product in the multi-product dose combination of a Recommendation.

    The optimizer (linprog) returns a dictionary {product: cantidad}. For
    every product with cantidad > 0, the recommendation flow computes a
    dose row via ``compute_dose`` and persists it here.

    Multi-tenant isolation is enforced via the parent Recommendation
    -> Lot -> Farm -> Organization chain (no org_id directly on this
    table to keep it denormalized and cheap to read in bulk).
    """

    __tablename__ = "recommendation_doses"
    id = db.Column(db.Integer, primary_key=True)
    recommendation_id = db.Column(
        db.Integer,
        db.ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = db.Column(
        db.Integer, db.ForeignKey("products.id"), nullable=False, index=True
    )
    product_name = db.Column(db.String(100), nullable=False)
    dose_per_ha = db.Column(db.Float, nullable=True)  # NULL when foliar (gap P1)
    dose_unit = db.Column(db.String(8), nullable=True)  # 'kg/ha' | 'L/ha' | NULL
    cost_per_ha = db.Column(db.Float, nullable=False, default=0.0)
    application_mode = db.Column(
        db.String(16), nullable=False, default="edaphic"
    )  # 'edaphic' | 'foliar' | 'unknown'
    application_type = db.Column(
        db.String(16), nullable=False, default="unknown"
    )  # 'powder' | 'liquid' | 'unknown'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    recommendation = db.relationship(
        "Recommendation", backref=db.backref("doses", lazy="dynamic")
    )
    product = db.relationship("Product")

    __table_args__ = (
        db.Index("ix_recommendation_doses_rec_prod", "recommendation_id", "product_id"),
    )

    def __repr__(self):
        return (
            f"<RecommendationDose rec={self.recommendation_id} "
            f"product={self.product_name} dose={self.dose_per_ha} {self.dose_unit}>"
        )

    def to_dict(self):
        return {
            "id": self.id,
            "recommendation_id": self.recommendation_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "dose_per_ha": self.dose_per_ha,
            "dose_unit": self.dose_unit,
            "cost_per_ha": self.cost_per_ha,
            "application_mode": self.application_mode,
            "application_type": self.application_type,
        }

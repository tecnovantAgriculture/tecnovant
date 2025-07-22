from marshmallow import Schema, ValidationError, fields, validates

from app.core.schemas import OrganizationSchema


class NutrientSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    symbol = fields.Str(required=True)
    unit = fields.Str(required=True)
    org_id = fields.Int()
    description = fields.Str(allow_none=True)
    cv = fields.Float(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class FarmSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    org_id = fields.Int(required=True)
    org_name = fields.Str(dump_only=True)
    lots = fields.List(fields.Str(), dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class LotSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    area = fields.Float(required=True)
    farm_id = fields.Int(required=True)
    farm_name = fields.Method("get_farm_name", dump_only=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

    def get_farm_name(self, obj):
        return getattr(obj.farm, "name", "")


class CropSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class LotCropSchema(Schema):
    id = fields.Int(dump_only=True)
    lot_id = fields.Int(required=True)
    crop_id = fields.Int(required=True)
    start_date = fields.Date(required=True)
    end_date = fields.Date(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class CommonAnalysisSchema(Schema):
    id = fields.Int(dump_only=True)
    date = fields.Date(required=True)
    lot_id = fields.Int(required=True)
    protein = fields.Float(allow_none=True)
    rest = fields.Float(allow_none=True)
    rest_days = fields.Int(allow_none=True)
    month = fields.Int(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class SoilAnalysisSchema(Schema):
    id = fields.Int(dump_only=True)
    common_analysis_id = fields.Int(required=True)
    energy = fields.Float(allow_none=True)
    grazing = fields.Int(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class NutrientSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    symbol = fields.Str(required=True)
    unit = fields.Str(required=True)
    description = fields.Str(allow_none=True)
    category = fields.Str()
    cv = fields.Float(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class LeafAnalysisSchema(Schema):
    id = fields.Int(dump_only=True)
    common_analysis_id = fields.Int(required=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class NutrientApplicationSchema(Schema):
    id = fields.Int(dump_only=True)
    date = fields.Date(required=True)
    lot_id = fields.Int(required=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class ObjectiveSchema(Schema):
    id = fields.Int(dump_only=True)
    crop_id = fields.Int(required=True)
    target_value = fields.Float(required=True)
    protein = fields.Float(allow_none=True)
    rest = fields.Float(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class ProductionSchema(Schema):
    id = fields.Int(dump_only=True)
    date = fields.Date(required=True)
    lot_id = fields.Int(required=True)
    area = fields.Float(allow_none=True)
    production_kg = fields.Float(allow_none=True)
    bags = fields.Int(allow_none=True)
    harvest = fields.Str(allow_none=True)
    month = fields.Int(allow_none=True)
    variety = fields.Str(allow_none=True)
    price_per_kg = fields.Float(allow_none=True)
    protein_65dde = fields.Float(allow_none=True)
    discount = fields.Float(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class ProductSchema(Schema):
    id = fields.Int(dump_only=True)
    name = fields.Str(required=True)
    description = fields.Str(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class ProductContributionSchema(Schema):
    id = fields.Int(dump_only=True)
    product_id = fields.Int(required=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class ProductPriceSchema(Schema):
    id = fields.Int(dump_only=True)
    product_id = fields.Int(required=True)
    price = fields.Float(required=True)
    supplier = fields.Str(allow_none=True)
    start_date = fields.Date(required=True)
    end_date = fields.Date(allow_none=True)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)


class RecommendationSchema(Schema):
    id = fields.Int(dump_only=True)
    lot_id = fields.Int(required=True)
    date = fields.Date(required=True)
    recommendation = fields.Str(required=True)
    applied = fields.Bool(missing=False)
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

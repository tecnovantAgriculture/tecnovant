"""REST API endpoints for foliage-related resources."""

from flask import Response, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required
from sqlalchemy.orm import joinedload

from app.core.models import RoleEnum
from app.extensions import db
from app.helpers.csv_handler import CsvHandler

from . import foliage_api as api
from .controller import (
    CommonAnalysisView,
    CropView,
    FarmView,
    LeafAnalysisView,
    LotCropView,
    LotView,
    NutrientApplicationView,
    NutrientView,
    ObjectiveView,
    ProductContributionView,
    ProductionView,
    ProductPriceView,
    ProductView,
    SoilAnalysisView,
)
from .csv_controller import CropCsvImportView
from .models import (
    CommonAnalysis,
    Crop,
    Farm,
    LeafAnalysis,
    Lot,
    LotCrop,
    Nutrient,
    NutrientApplication,
    Objective,
    Product,
    ProductContribution,
    Production,
    ProductPrice,
    SoilAnalysis,
    leaf_analysis_nutrients,
    nutrient_application_nutrients,
    objective_nutrients,
    product_contribution_nutrients,
)

# 👌
farm_view = FarmView.as_view("farms_view")
api.add_url_rule("/farms/", view_func=farm_view, methods=["GET", "POST", "DELETE"])
api.add_url_rule(
    "/farms/<int:id>", view_func=farm_view, methods=["GET", "PUT", "DELETE"]
)

# 👌
lot_view = LotView.as_view("lots_view")
api.add_url_rule("/lots/", view_func=lot_view, methods=["GET", "POST", "PUT", "DELETE"])
api.add_url_rule("/lots/<int:id>", view_func=lot_view, methods=["GET", "PUT", "DELETE"])

# 👌
crop_view = CropView.as_view("crops_view")
api.add_url_rule("/crops/", view_func=crop_view, methods=["GET", "POST", "DELETE"])
api.add_url_rule(
    "/crops/<int:id>", view_func=crop_view, methods=["GET", "PUT", "DELETE"]
)


# 👌
nutrient_view = NutrientView.as_view("nutrients")
api.add_url_rule(
    "/nutrients/", view_func=nutrient_view, methods=["GET", "POST", "DELETE"]
)
api.add_url_rule(
    "/nutrients/<int:id>", view_func=nutrient_view, methods=["GET", "PUT", "DELETE"]
)

# 👌
lot_crop_view = LotCropView.as_view("lot_crops")
api.add_url_rule(
    "/lots_crops/", view_func=lot_crop_view, methods=["GET", "POST", "DELETE"]
)
api.add_url_rule(
    "/lots_crops/<int:id>", view_func=lot_crop_view, methods=["GET", "PUT", "DELETE"]
)


# 👌
objective_view = ObjectiveView.as_view("objectives")
api.add_url_rule(
    "/objectives/", view_func=objective_view, methods=["GET", "POST", "DELETE"]
)
api.add_url_rule(
    "/objectives/<int:id>", view_func=objective_view, methods=["GET", "PUT", "DELETE"]
)

# 👌
product_view = ProductView.as_view("products")
api.add_url_rule(
    "/products/", view_func=product_view, methods=["GET", "POST", "DELETE"]
)
api.add_url_rule(
    "/products/<int:id>", view_func=product_view, methods=["GET", "PUT", "DELETE"]
)

# 👌
product_contribution_view = ProductContributionView.as_view("product_contributions")
api.add_url_rule(
    "/products_contributions/",
    view_func=product_contribution_view,
    methods=["GET", "POST", "DELETE"],
)
api.add_url_rule(
    "/products_contributions/<int:id>",
    view_func=product_contribution_view,
    methods=["GET", "PUT", "DELETE"],
)

# 👌
product_price_view = ProductPriceView.as_view("product_price_view")
api.add_url_rule(
    "/product_prices/", view_func=product_price_view, methods=["GET", "POST", "DELETE"]
)
api.add_url_rule(
    "/product_prices/<int:id>",
    view_func=product_price_view,
    methods=["GET", "PUT", "DELETE"],
)

# 👌
common_analysis_view = CommonAnalysisView.as_view("common_analyses")
api.add_url_rule(
    "/common_analyses/",
    view_func=common_analysis_view,
    methods=["GET", "POST", "DELETE"],
)
api.add_url_rule(
    "/common_analyses/<int:id>",
    view_func=common_analysis_view,
    methods=["GET", "PUT", "DELETE"],
)

# 👌
leaf_analysis_view = LeafAnalysisView.as_view("leaf_analyses")
api.add_url_rule(
    "/leaf_analyses/", view_func=leaf_analysis_view, methods=["GET", "POST", "DELETE"]
)
api.add_url_rule(
    "/leaf_analyses/<int:id>",
    view_func=leaf_analysis_view,
    methods=["GET", "PUT", "DELETE"],
)

# 👌
soil_analysis_view = SoilAnalysisView.as_view("soil_analysis")
api.add_url_rule(
    "/soil_analyses/", view_func=soil_analysis_view, methods=["GET", "POST", "DELETE"]
)
api.add_url_rule(
    "/soil_analyses/<int:id>",
    view_func=soil_analysis_view,
    methods=["GET", "PUT", "DELETE"],
)

# 👌
nutrient_application_view = NutrientApplicationView.as_view("nutrient_applications")
api.add_url_rule(
    "/nutrient_applications/",
    view_func=nutrient_application_view,
    methods=["GET", "POST", "DELETE"],
)
api.add_url_rule(
    "/nutrient_applications/<int:id>",
    view_func=nutrient_application_view,
    methods=["GET", "PUT", "DELETE"],
)

#
production_view = ProductionView.as_view("production_view")
api.add_url_rule(
    "/production/", view_func=production_view, methods=["GET", "POST", "DELETE"]
)
api.add_url_rule(
    "/production/<int:id>",
    view_func=nutrient_application_view,
    methods=["GET", "PUT", "DELETE"],
)


# ---------------------------------------------------------------------------
# CSV helper endpoints
# ---------------------------------------------------------------------------


@api.route("/csv/upload", methods=["POST"])
@jwt_required()
def upload_csv():
    """Upload a CSV file and return the parsed data."""
    if "file" not in request.files:
        return jsonify(error="No file part"), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify(error="No selected file"), 400

    handler = CsvHandler()
    try:
        data = handler.handle_csv_upload(file)
        return jsonify(data), 200
    except Exception as exc:
        return jsonify(error=str(exc)), 400


@api.route("/csv/download")
@jwt_required()
def download_csv():
    """Download CSV representation of simple resources."""
    resource = request.args.get("resource", "farms")
    handler = CsvHandler()
    org_ids = _accessible_org_ids(get_jwt())

    if resource == "farms":
        farm_q = Farm.query
        if org_ids is not None:
            farm_q = farm_q.filter(Farm.org_id.in_(org_ids))
        rows = [
            {
                "id": farm.id,
                "name": farm.name,
                "org_id": farm.org_id,
            }
            for farm in farm_q.all()
        ]
    elif resource == "crops":
        rows = [
            {
                "id": crop.id,
                "name": crop.name,
            }
            for crop in Crop.query.all()
        ]
    elif resource == "lots":
        lot_q = Lot.query
        if org_ids is not None:
            lot_q = lot_q.join(Farm).filter(Farm.org_id.in_(org_ids))
        rows = [
            {
                "id": lot.id,
                "name": lot.name,
                "farm_id": lot.farm_id,
            }
            for lot in lot_q.all()
        ]
    elif resource == "nutrients":
        rows = [
            {
                "id": n.id,
                "name": n.name,
                "symbol": n.symbol,
                "unit": n.unit,
                "description": n.description or "",
                "cv": n.cv or "",
            }
            for n in Nutrient.query.all()
        ]
    elif resource == "products":
        rows = [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description or "",
                "application_type": p.application_type,
                "created_at": str(p.created_at),
                "updated_at": str(p.updated_at),
            }
            for p in Product.query.all()
        ]
    else:
        return jsonify(error="Unknown resource"), 400

    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={resource}.csv"},
    )


# ---------------------------------------------------------------------------
# Dedicated CSV download endpoints (Type B — complex entities)
# ---------------------------------------------------------------------------


def _accessible_org_ids(claims):
    """Return a set of org_ids this user can access, or None for admin (all)."""
    role = claims.get("rol")
    if role == RoleEnum.ADMINISTRATOR.value:
        return None
    if role == RoleEnum.RESELLER.value:
        from app.core.models import ResellerPackage

        rp = ResellerPackage.query.filter_by(reseller_id=claims.get("org_id")).first()
        if rp:
            return {org.id for org in rp.organizations}
        return set()
    orgs = claims.get("organizations", [])
    if isinstance(orgs, list) and orgs and isinstance(orgs[0], dict):
        return {o["id"] for o in orgs}
    return set()


def _nutrient_name_map():
    """Return a dict {nutrient_id: name} for all nutrients (shared catalog)."""
    return {n.id: n.name for n in Nutrient.query.all()}


@api.route("/objectives/csv/download")
@jwt_required()
def download_objectives_csv():
    """Download CSV of objectives with nutrient target columns."""
    nutrient_map = _nutrient_name_map()
    objectives = (
        Objective.query.options(joinedload(Objective.crop))
        .order_by(Objective.id.asc())
        .all()
    )
    handler = CsvHandler()
    if not objectives:
        csv_data = handler.export_to_csv([])
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=objectives.csv"},
        )

    rows = []
    for obj in objectives:
        row = {
            "id": obj.id,
            "crop_name": obj.crop.name if obj.crop else "",
            "target_value": obj.target_value,
            "protein": obj.protein or "",
            "rest": obj.rest or "",
            "created_at": str(obj.created_at),
            "updated_at": str(obj.updated_at),
        }
        # build nutrient value lookup from association table
        assoc_rows = (
            db.session.query(objective_nutrients).filter_by(objective_id=obj.id).all()
        )
        for ar in assoc_rows:
            row[f"nutrient_{ar.nutrient_id}"] = ar.target_value or ""
        for nid in sorted(nutrient_map):
            row.setdefault(f"nutrient_{nid}", "")
        rows.append(row)

    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=objectives.csv"},
    )


@api.route("/product-contributions/csv/download")
@jwt_required()
def download_product_contributions_csv():
    """Download CSV of product contributions with nutrient contribution columns."""
    nutrient_map = _nutrient_name_map()
    contributions = (
        ProductContribution.query.options(joinedload(ProductContribution.product))
        .order_by(ProductContribution.id.asc())
        .all()
    )
    handler = CsvHandler()
    if not contributions:
        csv_data = handler.export_to_csv([])
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": "attachment; "
                "filename=product_contributions.csv",
            },
        )

    rows = []
    for pc in contributions:
        row = {
            "id": pc.id,
            "product_name": pc.product.name if pc.product else "",
            "created_at": str(pc.created_at),
            "updated_at": str(pc.updated_at),
        }
        assoc_rows = (
            db.session.query(product_contribution_nutrients)
            .filter_by(product_contribution_id=pc.id)
            .all()
        )
        for ar in assoc_rows:
            row[f"nutrient_{ar.nutrient_id}"] = ar.contribution or ""
        for nid in sorted(nutrient_map):
            row.setdefault(f"nutrient_{nid}", "")
        rows.append(row)

    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; " "filename=product_contributions.csv",
        },
    )


@api.route("/product-prices/csv/download")
@jwt_required()
def download_product_prices_csv():
    """Download CSV of product prices."""
    prices = (
        ProductPrice.query.options(joinedload(ProductPrice.product))
        .order_by(ProductPrice.id.asc())
        .all()
    )
    rows = [
        {
            "id": pp.id,
            "product_name": pp.product.name if pp.product else "",
            "price": pp.price,
            "supplier": pp.supplier or "",
            "start_date": str(pp.start_date) if pp.start_date else "",
            "end_date": str(pp.end_date) if pp.end_date else "",
            "price_unit": pp.price_unit,
            "created_at": str(pp.created_at),
            "updated_at": str(pp.updated_at),
        }
        for pp in prices
    ]
    handler = CsvHandler()
    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=product_prices.csv",
        },
    )


@api.route("/lot-crops/csv/download")
@jwt_required()
def download_lot_crops_csv():
    """Download CSV of lot crops scoped by org."""
    claims = get_jwt()
    org_ids = _accessible_org_ids(claims)
    query = (
        LotCrop.query.options(
            joinedload(LotCrop.lot).joinedload(Lot.farm),
            joinedload(LotCrop.crop),
        )
        .join(LotCrop.lot)
        .join(Lot.farm)
        .order_by(LotCrop.id.asc())
    )
    if org_ids is not None:
        query = query.filter(Farm.org_id.in_(org_ids))
    rows = [
        {
            "id": lc.id,
            "farm_name": lc.lot.farm.name if lc.lot and lc.lot.farm else "",
            "lot_name": lc.lot.name if lc.lot else "",
            "crop_name": lc.crop.name if lc.crop else "",
            "start_date": str(lc.start_date) if lc.start_date else "",
            "end_date": str(lc.end_date) if lc.end_date else "",
        }
        for lc in query.all()
    ]
    handler = CsvHandler()
    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=lot_crops.csv",
        },
    )


@api.route("/common-analyses/csv/download")
@jwt_required()
def download_common_analyses_csv():
    """Download CSV of common analyses scoped by org."""
    claims = get_jwt()
    org_ids = _accessible_org_ids(claims)
    query = (
        CommonAnalysis.query.options(
            joinedload(CommonAnalysis.lot).joinedload(Lot.farm)
        )
        .join(CommonAnalysis.lot)
        .join(Lot.farm)
        .order_by(CommonAnalysis.id.asc())
    )
    if org_ids is not None:
        query = query.filter(Farm.org_id.in_(org_ids))
    rows = [
        {
            "id": ca.id,
            "date": str(ca.date) if ca.date else "",
            "farm_name": ca.lot.farm.name if ca.lot and ca.lot.farm else "",
            "lot_name": ca.lot.name if ca.lot else "",
            "lot_area": ca.lot.area if ca.lot else "",
            "energy": ca.energy or "",
            "protein": ca.protein or "",
            "yield_estimate": ca.yield_estimate or "",
            "rest": ca.rest or "",
            "rest_days": ca.rest_days or "",
            "month": ca.month or "",
            "created_at": str(ca.created_at),
            "updated_at": str(ca.updated_at),
        }
        for ca in query.all()
    ]
    handler = CsvHandler()
    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=common_analyses.csv",
        },
    )


@api.route("/soil-analyses/csv/download")
@jwt_required()
def download_soil_analyses_csv():
    """Download CSV of soil analyses scoped by org."""
    claims = get_jwt()
    org_ids = _accessible_org_ids(claims)
    query = (
        SoilAnalysis.query.options(
            joinedload(SoilAnalysis.common_analysis)
            .joinedload(CommonAnalysis.lot)
            .joinedload(Lot.farm),
        )
        .join(SoilAnalysis.common_analysis)
        .join(CommonAnalysis.lot)
        .join(Lot.farm)
        .order_by(SoilAnalysis.id.asc())
    )
    if org_ids is not None:
        query = query.filter(Farm.org_id.in_(org_ids))
    rows = [
        {
            "id": sa.id,
            "common_analysis_id": sa.common_analysis_id,
            "energy": sa.energy or "",
            "grazing": sa.grazing or "",
            "created_at": str(sa.created_at),
            "updated_at": str(sa.updated_at),
        }
        for sa in query.all()
    ]
    handler = CsvHandler()
    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=soil_analyses.csv",
        },
    )


@api.route("/leaf-analyses/csv/download")
@jwt_required()
def download_leaf_analyses_csv():
    """Download CSV of leaf analyses with nutrient value columns, scoped by org."""
    nutrient_map = _nutrient_name_map()
    claims = get_jwt()
    org_ids = _accessible_org_ids(claims)
    query = (
        LeafAnalysis.query.options(
            joinedload(LeafAnalysis.common_analysis)
            .joinedload(CommonAnalysis.lot)
            .joinedload(Lot.farm),
        )
        .join(LeafAnalysis.common_analysis)
        .join(CommonAnalysis.lot)
        .join(Lot.farm)
        .order_by(LeafAnalysis.id.asc())
    )
    if org_ids is not None:
        query = query.filter(Farm.org_id.in_(org_ids))
    analyses = query.all()
    handler = CsvHandler()
    if not analyses:
        csv_data = handler.export_to_csv([])
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=leaf_analyses.csv",
            },
        )

    rows = []
    for la in analyses:
        ca = la.common_analysis
        row = {
            "id": la.id,
            "common_analysis_display": f"CA-{ca.id}" if ca else "",
            "farm_name": ca.lot.farm.name if ca and ca.lot and ca.lot.farm else "",
            "lot_name": ca.lot.name if ca and ca.lot else "",
            "created_at": str(la.created_at),
            "updated_at": str(la.updated_at),
        }
        assoc_rows = (
            db.session.query(leaf_analysis_nutrients)
            .filter_by(leaf_analysis_id=la.id)
            .all()
        )
        for ar in assoc_rows:
            row[f"nutrient_{ar.nutrient_id}"] = ar.value or ""
        for nid in sorted(nutrient_map):
            row.setdefault(f"nutrient_{nid}", "")
        rows.append(row)

    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=leaf_analyses.csv",
        },
    )


@api.route("/nutrient-applications/csv/download")
@jwt_required()
def download_nutrient_applications_csv():
    """Download CSV of nutrient applications with quantity columns, scoped by org."""
    nutrient_map = _nutrient_name_map()
    claims = get_jwt()
    org_ids = _accessible_org_ids(claims)
    query = (
        NutrientApplication.query.options(
            joinedload(NutrientApplication.lot).joinedload(Lot.farm)
        )
        .join(NutrientApplication.lot)
        .join(Lot.farm)
        .order_by(NutrientApplication.id.asc())
    )
    if org_ids is not None:
        query = query.filter(Farm.org_id.in_(org_ids))
    applications = query.all()
    handler = CsvHandler()
    if not applications:
        csv_data = handler.export_to_csv([])
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={
                "Content-Disposition": "attachment; "
                "filename=nutrient_applications.csv",
            },
        )

    rows = []
    for na in applications:
        row = {
            "id": na.id,
            "date": str(na.date) if na.date else "",
            "farm_name": na.lot.farm.name if na.lot and na.lot.farm else "",
            "lot_name": na.lot.name if na.lot else "",
            "created_at": str(na.created_at),
            "updated_at": str(na.updated_at),
        }
        assoc_rows = (
            db.session.query(nutrient_application_nutrients)
            .filter_by(nutrient_application_id=na.id)
            .all()
        )
        for ar in assoc_rows:
            row[f"nutrient_{ar.nutrient_id}"] = ar.quantity or ""
        for nid in sorted(nutrient_map):
            row.setdefault(f"nutrient_{nid}", "")
        rows.append(row)

    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; " "filename=nutrient_applications.csv",
        },
    )


@api.route("/productions/csv/download")
@jwt_required()
def download_productions_csv():
    """Download CSV of productions scoped by org."""
    claims = get_jwt()
    org_ids = _accessible_org_ids(claims)
    query = (
        Production.query.options(joinedload(Production.lot).joinedload(Lot.farm))
        .join(Production.lot)
        .join(Lot.farm)
        .order_by(Production.id.asc())
    )
    if org_ids is not None:
        query = query.filter(Farm.org_id.in_(org_ids))
    rows = [
        {
            "id": p.id,
            "farm_name": p.lot.farm.name if p.lot and p.lot.farm else "",
            "lot_name": p.lot.name if p.lot else "",
            "date": str(p.date) if p.date else "",
            "area": p.area or "",
            "production_kg": p.production_kg or "",
            "bags": p.bags or "",
            "harvest": p.harvest or "",
            "month": p.month or "",
            "variety": p.variety or "",
            "price_per_kg": p.price_per_kg or "",
            "protein_65dde": p.protein_65dde or "",
            "discount": p.discount or "",
        }
        for p in query.all()
    ]
    handler = CsvHandler()
    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=productions.csv",
        },
    )


# ---------------------------------------------------------------------------
# CSV upload / import
# ---------------------------------------------------------------------------
crop_csv_import_view = CropCsvImportView.as_view("crops_csv_import")
api.add_url_rule(
    "/crops/csv/import",
    view_func=crop_csv_import_view,
    methods=["POST"],
)

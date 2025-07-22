"""REST API endpoints for foliage-related resources."""

from flask import Response, jsonify, request

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
from .models import Crop, Farm, Lot

# 👌
farm_view = FarmView.as_view("farms_view")
api.add_url_rule("/farms/", view_func=farm_view, methods=["GET", "POST", "DELETE"])
api.add_url_rule(
    "/farms/<int:id>", view_func=farm_view, methods=["GET", "PUT", "DELETE"]
)

# 👌
lot_view = LotView.as_view("lots_view")
api.add_url_rule("/lots/", view_func=lot_view, methods=["GET", "POST", "DELETE"])
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
def download_csv():
    """Download CSV representation of simple resources."""
    resource = request.args.get("resource", "farms")
    handler = CsvHandler()

    if resource == "farms":
        rows = [
            {
                "id": farm.id,
                "name": farm.name,
                "org_id": farm.org_id,
            }
            for farm in Farm.query.all()
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
        rows = [
            {
                "id": lot.id,
                "name": lot.name,
                "farm_id": lot.farm_id,
            }
            for lot in Lot.query.all()
        ]
    else:
        return jsonify(error="Unknown resource"), 400

    csv_data = handler.export_to_csv(rows)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={resource}.csv"},
    )


# CSV import view
crop_csv_import_view = CropCsvImportView.as_view("crops_csv_import")
api.add_url_rule(
    "/crops/csv/import",
    view_func=crop_csv_import_view,
    methods=["POST"],
)

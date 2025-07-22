"""Controllers for CSV-related operations."""

from flask import jsonify, request
from flask.views import MethodView
from flask_jwt_extended import jwt_required

from app.core.controller import check_permission
from app.extensions import db

from .crop_csv_helper import CropCsvImporter


class CropCsvImportView(MethodView):
    """View to import crops from an uploaded CSV file."""

    decorators = [jwt_required()]

    @check_permission(required_roles=["administrator", "reseller"])
    def post(self):
        """Create or update crops from a CSV file."""
        if "file" not in request.files:
            return jsonify(error="No file part"), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify(error="No selected file"), 400

        importer = CropCsvImporter()
        try:
            rows = importer.handle_csv_upload(file)
            inserted, updated = importer.apply_rows(rows)
            db.session.commit()
            return jsonify({"inserted": inserted, "updated": updated}), 200
        except Exception as exc:
            db.session.rollback()
            return jsonify(error=str(exc)), 400

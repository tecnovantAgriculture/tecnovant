from app.extensions import db
from app.helpers.csv_handler import CsvHandler

from .models import Crop


class CropCsvImporter(CsvHandler):
    """Handle CSV rows and map them into Crop models."""

    def apply_rows(self, rows):
        """Insert or update crops from parsed CSV rows.

        Args:
            rows (list): Rows returned by ``import_from_csv`` or ``handle_csv_upload``.
        Returns:
            tuple: (inserted_count, updated_count)
        """
        inserted = 0
        updated = 0
        for row in rows:
            name = None
            if isinstance(row, dict):
                name = row.get("name")
            elif isinstance(row, (list, tuple)) and row:
                name = row[0]
            if not name:
                continue
            crop = Crop.query.filter_by(name=name).first()
            if crop:
                crop.name = name
                updated += 1
            else:
                db.session.add(Crop(name=name))
                inserted += 1
        return inserted, updated

"""Importa la hoja PROGRAMACION de operacion_tecnovant.xlsx para Tecnocant svc S.A.S.

Uso:
    python scripts/import_tecnocant_operations.py --dry-run
    python scripts/import_tecnocant_operations.py
"""

import argparse
import hashlib
import re
import secrets
import sys
import unicodedata
import zipfile
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.core.models import (
    MaintenanceDrone,
    OperationBillingRecord,
    OperationalActivity,
    Organization,
    PilotProfile,
    User,
)

DATA_PATH = Path(__file__).resolve().parents[1] / "import_data" / "operacion_tecnovant.xlsx"
ORGANIZATION_NAME = "Tecnocant svc S.A.S"
USER_NAME = "Tecnocant svc S.A.S"
SOURCE_NAME = "operacion_tecnovant.xlsx:PROGRAMACION"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def normalized(value):
    value = unicodedata.normalize("NFKD", clean(value))
    return "".join(char for char in value if not unicodedata.combining(char)).upper()


def column_index(reference):
    letters = re.match(r"[A-Z]+", reference).group(0)
    result = 0
    for letter in letters:
        result = result * 26 + ord(letter) - 64
    return result - 1


def cell_value(cell, shared_strings):
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//m:t", NS))
    value_node = cell.find("m:v", NS)
    if value_node is None:
        return None
    value = value_node.text
    if cell_type == "s":
        return shared_strings[int(value)]
    if cell_type == "b":
        return value == "1"
    return value


def read_rows(path):
    with zipfile.ZipFile(path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = [
                "".join(node.text or "" for node in item.findall(".//m:t", NS))
                for item in root.findall("m:si", NS)
            ]

        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship")
        }
        sheet_path = None
        for sheet in workbook.findall("m:sheets/m:sheet", NS):
            if normalized(sheet.attrib["name"]) == "PROGRAMACION":
                target = targets[sheet.attrib[f"{{{REL_NS}}}id"]]
                sheet_path = target.lstrip("/")
                if not sheet_path.startswith("xl/"):
                    sheet_path = f"xl/{sheet_path}"
                break
        if not sheet_path:
            raise RuntimeError("No se encontro la hoja PROGRAMACION")

        sheet = ET.fromstring(archive.read(sheet_path))
        xml_rows = sheet.findall(".//m:sheetData/m:row", NS)
        if not xml_rows:
            return []

        header_cells = {}
        for cell in xml_rows[0].findall("m:c", NS):
            header_cells[column_index(cell.attrib["r"])] = clean(cell_value(cell, shared_strings))
        max_column = max(header_cells)
        headers = [header_cells.get(index, "") for index in range(max_column + 1)]

        result = []
        for xml_row in xml_rows[1:]:
            values = {}
            for cell in xml_row.findall("m:c", NS):
                index = column_index(cell.attrib["r"])
                if index <= max_column and headers[index]:
                    values[headers[index]] = cell_value(cell, shared_strings)
            values["_excel_row"] = int(xml_row.attrib["r"])
            result.append(values)
        return result


def decimal_value(value):
    value = clean(value).replace("$", "").replace(",", "").replace(" ", "")
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def int_value(value):
    number = decimal_value(value)
    return int(number) if number is not None else None


def excel_date(value):
    value = clean(value)
    if not value:
        return None
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
    except ValueError:
        for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, pattern).date()
            except ValueError:
                pass
    return None


def excel_time(value):
    value = clean(value)
    if not value:
        return None
    try:
        seconds = round((float(value) % 1) * 86400)
        return time((seconds // 3600) % 24, (seconds % 3600) // 60, seconds % 60)
    except ValueError:
        for pattern in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(value, pattern).time()
            except ValueError:
                pass
    return None


def slug(value):
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-zA-Z0-9]+", ".", value.lower()).strip(".") or "piloto"


def get_or_create_pilot(full_name, counters):
    full_name = clean(full_name) or "Sin piloto asignado"
    lookup = normalized(full_name)
    for pilot in PilotProfile.query.all():
        if normalized(pilot.full_name) == lookup:
            return pilot
    parts = full_name.split()
    base_username = slug(full_name)[:70]
    username = base_username
    suffix = 2
    while PilotProfile.query.filter_by(username=username).first():
        username = f"{base_username}.{suffix}"[:80]
        suffix += 1
    pilot = PilotProfile(
        username=username,
        password_hash=generate_password_hash(secrets.token_urlsafe(32)),
        first_name=parts[0],
        last_name=" ".join(parts[1:]) or "Importado",
        certification_status="Importado",
        status="active",
    )
    db.session.add(pilot)
    db.session.flush()
    counters["pilots_created"] += 1
    return pilot


def get_import_drone():
    serial = "TECNOCANT-OPERACIONES-IMPORT"
    drone = MaintenanceDrone.query.filter_by(serial_number=serial).first()
    if drone:
        return drone
    drone = MaintenanceDrone(
        serial_number=serial,
        brand="TecnoAgro",
        model="Operaciones Tecnocant importadas",
        flight_hours=0,
        status="Aeronavegable",
    )
    db.session.add(drone)
    db.session.flush()
    return drone


def row_fingerprint(row):
    fields = [
        row.get("ITEM"), row.get("FINCA"), row.get("POTRERO"), row.get("AREA"),
        row.get("FECHAPROGRAMACION"), row.get("FECHAPROGRAMACIÓN"),
        row.get("FECHA  EJECUCION"), row.get("FECHA  EJECUCIÓN"),
        row.get("CLIENTE"), row.get("PILOTO"), row.get("Hora inicio"), row.get("Hora Fin"),
    ]
    payload = "|".join(clean(value) for value in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_column(row, plain_name):
    target = normalized(plain_name)
    for key, value in row.items():
        if normalized(key) == target:
            return value
    return None


def import_rows(rows, dry_run=False):
    counters = {
        "rows_seen": 0,
        "rows_skipped": 0,
        "duplicates_skipped": 0,
        "pilots_created": 0,
        "activities_created": 0,
        "billing_records_created": 0,
    }

    organization = Organization.query.filter(
        db.func.lower(Organization.name) == ORGANIZATION_NAME.lower()
    ).first()
    if not organization:
        organization = Organization(
            name=ORGANIZATION_NAME,
            description="Organizacion operativa importada desde Operacion Tecnovant.xlsx",
            active=True,
        )
        db.session.add(organization)
        db.session.flush()

    user = User.query.filter(db.func.lower(User.username) == USER_NAME.lower()).first()
    if not user:
        raise RuntimeError(f"No existe el usuario {USER_NAME}")
    if organization not in user.organizations:
        user.organizations.append(organization)

    existing_records = {}
    for record in OperationBillingRecord.query.all():
        raw = record.raw_payload or {}
        if raw.get("source") == SOURCE_NAME and raw.get("import_key"):
            existing_records[raw["import_key"]] = record

    drone = get_import_drone()
    display_item = 0
    for row in rows:
        counters["rows_seen"] += 1
        item = int_value(find_column(row, "ITEM"))
        farm = clean(find_column(row, "FINCA"))
        final_client = clean(find_column(row, "CLIENTE"))
        area = decimal_value(find_column(row, "AREA"))
        invoice_total = decimal_value(find_column(row, "TOTAL FACTURA"))
        scheduled_date = excel_date(find_column(row, "FECHAPROGRAMACION"))
        executed_date = excel_date(find_column(row, "FECHA  EJECUCION"))
        if not farm or not (executed_date or scheduled_date) or (area is None and invoice_total is None):
            counters["rows_skipped"] += 1
            continue

        display_item += 1
        import_key = row_fingerprint(row)
        if import_key in existing_records:
            record = existing_records[import_key]
            record.raw_payload = {
                **(record.raw_payload or {}),
                "display_item": display_item,
                "item": item,
                "final_client": final_client,
            }
            counters["duplicates_skipped"] += 1
            continue

        pilot_name = clean(find_column(row, "PILOTO"))
        pilot = get_or_create_pilot(pilot_name, counters)
        operation_date = executed_date or scheduled_date
        start_time = excel_time(find_column(row, "Hora inicio")) or time(8, 0)
        end_time = excel_time(find_column(row, "Hora Fin"))
        operation_hours = decimal_value(find_column(row, "Tiempo operacion"))
        starts_at = datetime.combine(operation_date, start_time)
        if end_time:
            ends_at = datetime.combine(operation_date, end_time)
            if ends_at <= starts_at:
                ends_at += timedelta(days=1)
        else:
            minutes = int(operation_hours * 60) if operation_hours and operation_hours > 0 else 60
            ends_at = starts_at + timedelta(minutes=minutes)
        duration_minutes = max(1, int((ends_at - starts_at).total_seconds() // 60))

        paddock = clean(find_column(row, "POTRERO"))
        observations = clean(find_column(row, "OBSERVACIONES"))
        activity = OperationalActivity(
            title=(f"{farm} - {final_client}" if final_client else farm)[:140],
            operation_type="Aplicacion agricola",
            starts_at=starts_at,
            ends_at=ends_at,
            duration_minutes=duration_minutes,
            place=(f"{farm} - {paddock}" if paddock else farm)[:180],
            client_project=organization.name,
            farm_name=farm[:160],
            paddocks=paddock or None,
            area_hectares=area,
            lot_code=paddock[:80] if paddock else None,
            pilot_id=pilot.id,
            drone_id=drone.id,
            observations=((f"Cliente final: {final_client}. " if final_client else "") + observations).strip()[:500],
            status="completed" if executed_date else "scheduled",
            completed_at=ends_at if executed_date else None,
            created_by_id=user.id,
        )
        db.session.add(activity)
        db.session.flush()

        raw_payload = {
            "source": SOURCE_NAME,
            "import_key": import_key,
            "excel_row": row["_excel_row"],
            "item": item,
            "display_item": display_item,
            "final_client": final_client,
        }
        record = OperationBillingRecord(
            activity=activity,
            organization=organization,
            farm_name=farm[:160],
            paddock_name=paddock[:160] if paddock else None,
            area_hectares=area,
            scheduled_date=scheduled_date,
            executed_date=executed_date or scheduled_date,
            billing_cut=clean(find_column(row, "CORTE FACTURACION"))[:40] or None,
            billing_month=clean(find_column(row, "MES"))[:40] or None,
            unit_price=decimal_value(find_column(row, "PRECIO")),
            invoice_total=invoice_total,
            invoice_number=clean(find_column(row, "FACTURA"))[:80] or None,
            pilot_name=pilot_name[:160] or None,
            operation_hours=operation_hours,
            hectares_per_hour=decimal_value(find_column(row, "Ha's/Hora")),
            observations=observations or None,
            raw_payload=raw_payload,
        )
        db.session.add(record)
        counters["activities_created"] += 1
        counters["billing_records_created"] += 1
        existing_records[import_key] = record

    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return counters


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    rows = read_rows(DATA_PATH)
    app = create_app()
    with app.app_context():
        summary = import_rows(rows, dry_run=args.dry_run)
        summary["dry_run"] = args.dry_run
        summary["source_rows"] = len(rows)
        print(summary)


if __name__ == "__main__":
    main()
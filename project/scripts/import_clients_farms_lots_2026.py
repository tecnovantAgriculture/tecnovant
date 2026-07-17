import csv
import sys
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func

from app import create_app
from app.extensions import db
from app.core.models import Organization
from app.modules.foliage.models import Farm, Lot

DATA_PATH = Path(__file__).resolve().parents[1] / "import_data" / "clients_farms_lots_2026.tsv"
BASE_ORGANIZATION = "Tecnocant svc S.A.S"


BASE_ORGANIZATION = 'Tecnovant svc S.A.S'


def clean(value):
    return " ".join((value or "").strip().split())


def normalized(value):
    text = unicodedata.normalize("NFKD", clean(value)).encode("ascii", "ignore").decode("ascii")
    return text.casefold()


def parse_area(value):
    value = clean(value).replace(".", "").replace(",", ".")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def load_catalog():
    catalog = defaultdict(lambda: defaultdict(dict))
    with DATA_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            client = clean(row.get("CLIENTE"))
            farm = clean(row.get("FINCA"))
            paddock = clean(row.get("POTRERO"))
            if not client or not farm:
                continue
            farm_entry = catalog[client][farm]
            if paddock:
                area = parse_area(row.get("AREA"))
                previous = farm_entry.get(paddock, Decimal("0"))
                farm_entry[paddock] = max(previous, area)
    return catalog


def find_named(model, field, value, extra_filters=()):
    query = model.query
    for expression in extra_filters:
        query = query.filter(expression)
    return query.filter(func.lower(field) == value.casefold()).first()


def run():
    catalog = load_catalog()
    base = Organization.query.filter(func.lower(Organization.name) == BASE_ORGANIZATION.casefold()).first()
    if not base:
        raise RuntimeError(f"No existe la organización base: {BASE_ORGANIZATION}")
    base_users = list(base.users)
    counts = {"clients_created": 0, "farms_created": 0, "lots_created": 0, "lots_updated": 0}

    for client_name, farms in catalog.items():
        client = find_named(Organization, Organization.name, client_name)
        if not client:
            client = Organization(
                name=client_name,
                description=f"Cliente operativo importado desde {DATA_PATH.name}",
                active=True,
            )
            db.session.add(client)
            db.session.flush()
            counts["clients_created"] += 1
        for user in base_users:
            if not user.organizations.filter_by(id=client.id).first():
                user.organizations.append(client)

        for farm_name, lots in farms.items():
            farm = find_named(Farm, Farm.name, farm_name, (Farm.org_id == client.id,))
            if not farm:
                farm = Farm(name=farm_name, org_id=client.id)
                db.session.add(farm)
                db.session.flush()
                counts["farms_created"] += 1

            for lot_name, area in lots.items():
                lot = find_named(Lot, Lot.name, lot_name, (Lot.farm_id == farm.id,))
                area_value = float(area)
                if not lot:
                    lot = Lot(name=lot_name, area=area_value, farm_id=farm.id, active=True)
                    db.session.add(lot)
                    counts["lots_created"] += 1
                elif area_value > float(lot.area or 0):
                    lot.area = area_value
                    lot.active = True
                    counts["lots_updated"] += 1

    db.session.commit()
    print({**counts, "clients_total": len(catalog), "base_users_linked": len(base_users)})
    for client_name, farms in catalog.items():
        print(client_name, "fincas=", len(farms), "lotes=", sum(len(lots) for lots in farms.values()))


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        run()

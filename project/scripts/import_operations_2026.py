import csv
import re
import unicodedata
import sys
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

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
)

DATA_PATH = Path(__file__).resolve().parents[1] / 'import_data' / 'operations_2026.tsv'
MONTHS = {
    'ene': 1,
    'feb': 2,
    'mar': 3,
    'abr': 4,
    'may': 5,
    'jun': 6,
    'jul': 7,
    'ago': 8,
    'sep': 9,
    'oct': 10,
    'nov': 11,
    'dic': 12,
}


def clean(value):
    return (value or '').strip()


def parse_decimal(value):
    value = clean(value)
    if not value:
        return None
    value = value.replace('$', '').replace(' ', '').replace(',', '')
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def parse_int(value):
    try:
        return int(clean(value))
    except ValueError:
        return None


def parse_date(value):
    value = clean(value).lower()
    if not value:
        return None
    parts = value.split('-')
    if len(parts) != 3:
        return None
    day = int(parts[0])
    month = MONTHS.get(parts[1][:3])
    year = int(parts[2])
    year += 2000 if year < 100 else 0
    if not month:
        return None
    return datetime(year, month, day).date()


def parse_time(value):
    value = clean(value)
    if not value:
        return None
    for fmt in ('%H:%M:%S', '%H:%M'):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            pass
    return None


def slug(value):
    value = unicodedata.normalize('NFKD', value)
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r'[^a-zA-Z0-9]+', '.', value.lower()).strip('.')
    return value or 'piloto'


def get_or_create_pilot(full_name, counters):
    full_name = clean(full_name) or 'Sin piloto asignado'
    lookup = full_name.lower()
    for existing in PilotProfile.query.all():
        if existing.full_name.lower() == lookup:
            return existing
        if len(full_name.split()) == 1 and existing.first_name.lower() == lookup and existing.last_name == 'Importado':
            return existing

    parts = full_name.split()
    first_name = parts[0]
    last_name = ' '.join(parts[1:]) or 'Importado'
    base_username = slug(full_name)[:70]
    username = base_username
    suffix = 2
    while PilotProfile.query.filter_by(username=username).first():
        username = f'{base_username}.{suffix}'[:80]
        suffix += 1

    pilot = PilotProfile(
        username=username,
        password_hash=generate_password_hash('importado2026'),
        first_name=first_name,
        last_name=last_name,
        certification_status='Importado',
        status='active',
    )
    db.session.add(pilot)
    db.session.flush()
    counters['pilots_created'] += 1
    return pilot


def get_or_create_org(name, counters):
    name = clean(name)
    if not name:
        return None
    org = Organization.query.filter(db.func.lower(Organization.name) == name.lower()).first()
    if org:
        return org
    org = Organization(name=name, description='Cliente importado desde operaciones 2026', active=True)
    db.session.add(org)
    db.session.flush()
    counters['clients_created'] += 1
    return org


def get_import_drone():
    drone = MaintenanceDrone.query.filter_by(serial_number='OPERACIONES-IMPORT-2026').first()
    if drone:
        return drone
    drone = MaintenanceDrone(
        serial_number='OPERACIONES-IMPORT-2026',
        brand='TecnoAgro',
        model='Operaciones importadas 2026',
        flight_hours=0,
        status='Aeronavegable',
    )
    db.session.add(drone)
    db.session.flush()
    return drone


def activity_times(row, scheduled_date, executed_date):
    start_time = parse_time(row.get('Hora inicio')) or time(8, 0)
    duration_hours = parse_decimal(row.get('Tiempo operación')) or Decimal('0')
    end_time = parse_time(row.get('Hora Fin'))
    start_day = executed_date or scheduled_date
    if not start_day:
        return None, None, 0
    starts_at = datetime.combine(start_day, start_time)
    if end_time:
        ends_at = datetime.combine(start_day, end_time)
        if ends_at <= starts_at:
            ends_at += timedelta(days=1)
    else:
        minutes = int(duration_hours * Decimal(60)) if duration_hours > 0 else 60
        ends_at = starts_at + timedelta(minutes=minutes)
    minutes = max(1, int((ends_at - starts_at).total_seconds() // 60))
    return starts_at, ends_at, minutes


def load_rows():
    text = DATA_PATH.read_text(encoding='utf-8-sig')
    reader = csv.DictReader(text.splitlines(), delimiter='\t')
    for row in reader:
        yield {clean(k): clean(v) for k, v in row.items() if k is not None}


def import_rows():
    counters = {
        'rows_seen': 0,
        'rows_skipped': 0,
        'clients_created': 0,
        'pilots_created': 0,
        'activities_created': 0,
        'records_created': 0,
        'records_updated': 0,
    }
    drone = get_import_drone()

    for row in load_rows():
        item = parse_int(row.get('ITEM'))
        farm = clean(row.get('FINCA'))
        client_name = clean(row.get('CLIENTE'))
        area = parse_decimal(row.get('AREA'))
        invoice_total = parse_decimal(row.get('TOTAL FACTURA')) or Decimal('0')
        unit_price = parse_decimal(row.get('PRECIO'))
        pilot_name = clean(row.get('PILOTO'))
        counters['rows_seen'] += 1

        if not item or not farm or not client_name or (not area and invoice_total == 0):
            counters['rows_skipped'] += 1
            continue

        existing = OperationBillingRecord.query.filter_by(source_item=item).first()
        org = get_or_create_org(client_name, counters)
        pilot = get_or_create_pilot(pilot_name, counters)
        scheduled_date = parse_date(row.get('FECHAPROGRAMACIÓN'))
        executed_date = parse_date(row.get('FECHA  EJECUCIÓN')) or scheduled_date
        starts_at, ends_at, minutes = activity_times(row, scheduled_date, executed_date)
        if not starts_at or not ends_at:
            counters['rows_skipped'] += 1
            continue

        paddock = clean(row.get('POTRERO'))
        obs = clean(row.get('OBSERVACIONES'))
        invoice = clean(row.get('FACTURA'))
        place = farm if not paddock else f'{farm} - {paddock}'
        title = f'{farm} - {client_name}'
        activity_payload = {
            'title': title[:140],
            'operation_type': 'Aplicacion agricola',
            'starts_at': starts_at,
            'ends_at': ends_at,
            'duration_minutes': minutes,
            'place': place[:180],
            'client_project': client_name[:160],
            'pilot_id': pilot.id,
            'drone_id': drone.id,
            'observations': f'Item {item}. {obs}'.strip()[:500],
            'status': 'completed',
            'completed_at': ends_at,
        }

        if existing:
            activity = existing.activity
            for key, value in activity_payload.items():
                setattr(activity, key, value)
            record = existing
            counters['records_updated'] += 1
        else:
            activity = OperationalActivity(**activity_payload)
            db.session.add(activity)
            db.session.flush()
            record = OperationBillingRecord(activity=activity, source_item=item)
            db.session.add(record)
            counters['activities_created'] += 1
            counters['records_created'] += 1

        record.organization = org
        record.farm_name = farm[:160]
        record.paddock_name = paddock[:160] if paddock else None
        record.area_hectares = area
        record.scheduled_date = scheduled_date
        record.executed_date = executed_date
        record.billing_cut = clean(row.get('CORTE FACTURACIÓN'))[:40] or None
        record.billing_month = clean(row.get('MES'))[:40] or None
        record.unit_price = unit_price
        record.invoice_total = invoice_total
        record.invoice_number = invoice[:80] or None
        record.pilot_name = pilot_name[:160] or None
        record.operation_hours = parse_decimal(row.get('Tiempo operación'))
        record.hectares_per_hour = parse_decimal(row.get('Ha\'s/Hora'))
        record.observations = obs or None
        record.raw_payload = row

    db.session.commit()
    return counters


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()
        summary = import_rows()
        print(summary)
"""Landscape classification and takeoffs from a native, read-only snapshot.

This module never imports ``vs`` or measures geometry. The menu-command collector
owns UUID resolution, object-type checks, native record reads and measurements.
Native units must be established by that collector before passing quantities.
Classifications describe project scope, not when an object was drawn. A newly
drawn existing-house reference therefore remains ``existing`` and is excluded.
"""
from collections import Counter
from decimal import Decimal, localcontext
import math
import re
from uuid import UUID


RECORD_NAME = 'VWX_Landscape'
# Native text fields use NewField(record, field, default, 4, 0). Object identity
# is read from GetObjectUuid, never stored as a copied record-field identifier.
RECORD_FIELDS = {
    'status': 'Status', 'role': 'Role', 'category': 'Category',
    'material': 'Material', 'measurement': 'Measurement', 'unit': 'Unit', 'count_field': 'CountField',
    'assembly_id': 'AssemblyId', 'classification_source': 'ClassificationSource',
    'description': 'Description',
}
STATUSES = frozenset(('existing', 'new_proposed', 'remove', 'unknown'))
ROLES = frozenset(('item', 'assembly', 'assembly_part', 'reference', 'markup'))
MEASUREMENTS = {'plan_area': 'area', 'perimeter': 'length',
                'linear_length': 'length', 'count': 'count', 'plant_count': 'count'}
MAX_ITEMS = 5000

# Exact SI dimensions. Aliases and document display names are intentionally not
# accepted: ``ft2`` and ``ft`` cannot silently become interchangeable.
_LENGTH_METRES = {
    'mm': Decimal('0.001'), 'cm': Decimal('0.01'), 'm': Decimal('1'),
    'in': Decimal('0.0254'), 'ft': Decimal('0.3048'), 'yd': Decimal('0.9144'),
}
UNITS = {'each': ('count', Decimal(1))}
for _name, _metres in _LENGTH_METRES.items():
    for _kind, _power in (('length', 1), ('area', 2), ('volume', 3)):
        UNITS[_name + (str(_power) if _power > 1 else '')] = (_kind, _metres ** _power)
UNITS.update(acre=('area', Decimal('4046.8564224')), ha=('area', Decimal('10000')))


def _text(value, field, *, empty=False, limit=512):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ValueError('%s must be text of at most %d characters' % (field, limit))
    if value != value.strip() or (not empty and not value):
        raise ValueError('%s must be nonblank text without surrounding whitespace' % field)
    return value


def _number(value, field, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError('%s must be a finite number' % field)
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or (not zero and result == 0):
        raise ValueError('%s must be finite and %s' % (field, 'nonnegative' if zero else 'positive'))
    _json_number(result)
    return result


def _json_number(value):
    result = float(value)
    if not math.isfinite(result) or (value != 0 and result == 0):
        raise ValueError('quantity or cost exceeds the supported JSON numeric range')
    return result


def _uuid(value):
    if not isinstance(value, str):
        raise ValueError('object_id must be a UUID string')
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        raise ValueError('object_id must be a UUID string') from None
    if parsed.int == 0:
        raise ValueError('object_id must not be the nil UUID')
    return str(parsed)


def validate_metadata(metadata):
    """Validate explicit scope and measurement fields before any native writes.

    Description, classification_source and assembly_id may be omitted. CountField
    is required only for a plant_count read from a discovered native PIO field. No
    field defaults classify an object as new
    work; status, role and quantity basis must always be supplied deliberately.
    """
    if not isinstance(metadata, dict):
        raise ValueError('metadata must be an object')
    unknown = set(metadata) - set(RECORD_FIELDS)
    if unknown:
        raise ValueError('unknown metadata fields: ' + ', '.join(sorted(unknown)))
    optional = {'description', 'classification_source', 'assembly_id', 'count_field'}
    out = {key: _text(metadata.get(key, ''), key, empty=key in optional)
           for key in RECORD_FIELDS}
    if out['status'] not in STATUSES:
        raise ValueError('status must be existing, new_proposed, remove or unknown')
    if out['role'] not in ROLES:
        raise ValueError('role must be item, assembly, assembly_part, reference or markup')
    if out['measurement'] not in MEASUREMENTS:
        raise ValueError('measurement must be plan_area, perimeter, linear_length, count or plant_count')
    if out['unit'] not in UNITS or UNITS[out['unit']][0] != MEASUREMENTS[out['measurement']]:
        raise ValueError('unit does not match measurement')
    if out['assembly_id']:
        out['assembly_id'] = _uuid(out['assembly_id'])
    if (out['measurement'] == 'plant_count') != bool(out['count_field']):
        raise ValueError('count_field is required for plant_count and must be empty for other measurements')
    return out


def convert_coordinate_quantity(value, quantity_kind, units_per_inch, target_unit):
    """Convert an established native coordinate measurement to an explicit unit.

    For area, square the linear conversion; for volume, cube it. This helper
    does not establish that a particular SDK volume API uses coordinate units.
    ``ObjArea`` display units and an undocumented volume basis must not enter it.
    """
    if quantity_kind not in ('length', 'area', 'volume'):
        raise ValueError('coordinate conversion supports length, area or volume')
    if not isinstance(target_unit, str) or target_unit not in UNITS or UNITS[target_unit][0] != quantity_kind:
        raise ValueError('target_unit does not match quantity_kind')
    number = _number(value, 'quantity', zero=True)
    scale = _number(units_per_inch, 'units_per_inch')
    power = {'length': 1, 'area': 2, 'volume': 3}[quantity_kind]
    with localcontext() as context:
        context.prec = 64
        return _json_number(number * (Decimal('0.0254') / scale) ** power / UNITS[target_unit][1])


def _classification_key(row):
    category = _text(row.get('category'), 'category')
    material = _text(row.get('material'), 'material')
    kind = _text(row.get('quantity_kind'), 'quantity_kind')
    unit = _text(row.get('unit'), 'unit')
    if unit not in UNITS or UNITS[unit][0] != kind:
        raise ValueError('unit does not match quantity_kind')
    return category, material, kind, unit


def validate_prices(prices=None):
    """Validate explicit quotes before the collector does any native work.

    Exact category/material/dimension/unit matches only. Prices require a
    source and currency; no market price, unit or currency is inferred.
    """
    if prices is None:
        return []
    if not isinstance(prices, list) or len(prices) > MAX_ITEMS:
        raise ValueError('prices must be a list of at most %d quotes' % MAX_ITEMS)
    output, keys = [], set()
    allowed = {'category', 'material', 'quantity_kind', 'unit', 'unit_price', 'currency', 'source'}
    for row in prices:
        if not isinstance(row, dict) or set(row) - allowed:
            raise ValueError('each price must contain only documented quote fields')
        key = _classification_key(row)
        if key in keys:
            raise ValueError('duplicate or conflicting price for category/material/quantity_kind/unit')
        keys.add(key)
        amount = _number(row.get('unit_price'), 'unit_price', zero=True)
        currency = _text(row.get('currency'), 'currency')
        if re.fullmatch('[A-Z]{3}', currency) is None:
            raise ValueError('currency must be an explicit three-letter uppercase code')
        source = _text(row.get('source'), 'source', limit=2048)
        output.append(dict(zip(('category', 'material', 'quantity_kind', 'unit'), key),
                           unit_price=_json_number(amount), currency=currency, source=source))
    return output


def _snapshot_item(row):
    if row.get('status') != 'new_proposed':
        raise ValueError('not_new_proposed')
    if row.get('role') not in ('item', 'assembly'):
        raise ValueError('non_billable_role')
    assembly_id = row.get('assembly_id', '')
    if not isinstance(assembly_id, str):
        raise ValueError('assembly_id must be an empty string or a native object UUID')
    if assembly_id:
        # Collector-provided membership also excludes a child mislabeled item.
        _uuid(assembly_id)
        raise ValueError('assembly_member')
    if row.get('measurement_error'):
        raise ValueError('measurement_failed: ' + _text(row['measurement_error'], 'measurement_error'))
    key = _classification_key(row)
    amount = _number(row.get('quantity'), 'quantity')
    if key[2] == 'count' and amount != amount.to_integral_value():
        raise ValueError('count must be a positive integer from resolved objects or a native plant quantity field')
    source = _text(row.get('measurement_source'), 'measurement_source', limit=2048)
    item = dict(zip(('category', 'material', 'quantity_kind', 'unit'), key),
                object_id=_uuid(row.get('object_id')), status='new_proposed', role=row['role'],
                quantity=_json_number(amount), measurement_source=source)
    if 'description' in row:
        item['description'] = _text(row['description'], 'description', empty=True)
    if 'classification_source' in row:
        item['classification_source'] = _text(row['classification_source'], 'classification_source', empty=True)
    if 'measurement' in row:
        measurement = _text(row['measurement'], 'measurement')
        if measurement not in MEASUREMENTS or MEASUREMENTS[measurement] != key[2]:
            raise ValueError('measurement does not match quantity_kind')
        if measurement == 'count' and amount != 1:
            raise ValueError('object count must be one per native UUID; plant_count requires a discovered native field')
        item['measurement'] = measurement
        if measurement == 'plant_count':
            item['count_field'] = _text(row.get('count_field'), 'count_field')
    return item, amount, key


def build_takeoff(snapshots, prices=None):
    """Summarize native snapshots without mutations, implicit scope or pricing.

    Duplicate UUIDs exclude *every* occurrence, even contradictory records.
    Existing/removal/unknown objects, reference/markup/assembly parts, invalid
    measurements and incomplete classification are listed under ``excluded``.
    Different dimensions, units, materials and currencies are never merged.
    Cost totals are unrounded extensions of supplied quotes, excluding taxes,
    contingency and other unprovided allowances. Unpriced work stays visible.
    """
    if not isinstance(snapshots, list) or len(snapshots) > MAX_ITEMS:
        raise ValueError('snapshots must be a list of at most %d objects' % MAX_ITEMS)
    quotes = {_classification_key(row): row for row in validate_prices(prices)}
    identities = []
    for row in snapshots:
        try:
            identities.append(_uuid(row.get('object_id')) if isinstance(row, dict) else None)
        except ValueError:
            identities.append(None)
    occurrences = Counter(identity for identity in identities if identity is not None)
    items, excluded, groups, quantities, costs = [], [], {}, {}, {}
    used_prices = set()
    with localcontext() as context:
        context.prec = 64
        for index, (row, identity) in enumerate(zip(snapshots, identities)):
            try:
                if identity is None:
                    raise ValueError('invalid_object_uuid')
                if occurrences[identity] > 1:
                    raise ValueError('duplicate_object_uuid')
                item, amount, key = _snapshot_item(row)
            except ValueError as error:
                excluded.append({'index': index, 'object_id': identity, 'reason': str(error)})
                continue
            quote = quotes.get(key)
            item['pricing_status'] = 'priced' if quote else 'unpriced'
            if quote:
                used_prices.add(key)
                extended = amount * Decimal(str(quote['unit_price']))
                item.update(unit_price=quote['unit_price'], currency=quote['currency'],
                            price_source=quote['source'], cost=_json_number(extended))
                costs[quote['currency']] = costs.get(quote['currency'], Decimal(0)) + extended
            items.append(item)
            group = groups.setdefault(key, {'quantity': Decimal(0), 'object_ids': []})
            group['quantity'] += amount
            group['object_ids'].append(identity)
            quantities[key[2:]] = quantities.get(key[2:], Decimal(0)) + amount
        schedule = []
        for key, group in sorted(groups.items()):
            entry = dict(zip(('category', 'material', 'quantity_kind', 'unit'), key),
                         quantity=_json_number(group['quantity']),
                         object_ids=sorted(group['object_ids']))
            quote = quotes.get(key)
            entry['pricing_status'] = 'priced' if quote else 'unpriced'
            if quote:
                entry.update(unit_price=quote['unit_price'], currency=quote['currency'],
                             price_source=quote['source'],
                             cost=_json_number(group['quantity'] * Decimal(str(quote['unit_price']))))
            schedule.append(entry)
    priced_count = sum(item['pricing_status'] == 'priced' for item in items)
    return {
        'status': 'ok', 'scope': 'supplied_native_object_snapshot',
        'line_items': sorted(items, key=lambda item: item['object_id']), 'schedule': schedule,
        'quantity_totals': [{'quantity_kind': kind, 'unit': unit, 'quantity': _json_number(value)}
                            for (kind, unit), value in sorted(quantities.items())],
        'cost_totals': [{'currency': currency, 'cost': _json_number(value)}
                        for currency, value in sorted(costs.items())],
        'excluded': excluded,
        'unused_prices': [quotes[key] for key in sorted(set(quotes) - used_prices)],
        'summary': {'snapshot_objects': len(snapshots), 'included_objects': len(items),
                    'excluded_objects': len(excluded), 'priced_objects': priced_count,
                    'unpriced_objects': len(items) - priced_count,
                    'pricing_complete': bool(items) and priced_count == len(items)},
        'limitations': [
            'Only explicitly new_proposed item/assembly objects enter this takeoff.',
            'Quantities depend on the native collector and explicit project classification; geometry is not inferred from descriptions.',
            'Overlapping geometry or unreported assembly membership cannot be detected from scalar measurements.',
            'Costs use supplied quote sources and exact units, without currency conversion, taxes, contingency or inferred prices.',
        ],
    }

#!/usr/bin/env python3
"""Offline UA reporting. Standard library only; Python 3.10+."""
import argparse
import csv
import html
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

D = Decimal
KEY = ('date', 'ad_id', 'country', 'currency')
SCHEMAS = {
    'ads': KEY + ('spend', 'impressions', 'clicks'),
    'analytics': KEY + ('purchases', 'net_revenue', 'variable_costs'),
}
DEFAULTS = dict(min_spend=100, min_purchases=10, kill_romi=0,
                scale_romi=25, maturity_days=3)


def number(value, field):
    try:
        n = D(str(value))
    except InvalidOperation:
        raise ValueError(f'{field}: invalid number {value!r}') from None
    if not n.is_finite() or n < 0:
        raise ValueError(f'{field}: expected finite nonnegative number')
    if field in ('impressions', 'clicks', 'purchases') and n != n.to_integral_value():
        raise ValueError(f'{field}: expected integer')
    return n


def load(path, kind):
    """Require a unique daily ad/country/currency grain; never silently sum duplicates."""
    records = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f'{path}: missing or duplicate headers')
        missing = set(SCHEMAS[kind]) - set(reader.fieldnames)
        if missing:
            raise ValueError(f'{path}: missing columns: {", ".join(sorted(missing))}')
        for line, raw in enumerate(reader, 2):
            try:
                if None in raw or any(raw.get(k) is None for k in SCHEMAS[kind]):
                    raise ValueError('row width differs from header')
                row = {k: raw[k].strip() for k in SCHEMAS[kind]}
                if any(not row[k] for k in KEY):
                    raise ValueError('empty join key')
                if date.fromisoformat(row['date']).isoformat() != row['date']:
                    raise ValueError('date must be YYYY-MM-DD')
                if len(row['currency']) != 3 or not row['currency'].isascii() or not row['currency'].isupper() or not row['currency'].isalpha():
                    raise ValueError('currency must be a three-letter uppercase code')
                for k in SCHEMAS[kind][4:]:
                    row[k] = number(row[k], k)
                if kind == 'ads' and row['clicks'] > row['impressions']:
                    raise ValueError('clicks exceed impressions')
                key = tuple(row[k] for k in KEY)
                if key in records:
                    raise ValueError(f'duplicate key: {key}')
                records[key] = row
            except ValueError as exc:
                raise ValueError(f'{path}, line {line}: {exc}') from None
    if not records:
        raise ValueError(f'{path}: no data rows')
    return records


def ratio(a, b, multiplier=1):
    return a / b * multiplier if b else None


def analyze(ads, analytics, start, end, as_of, config):
    if start > end or end > as_of:
        raise ValueError('Expected start <= end <= as-of')
    cfg = dict(DEFAULTS, **config)
    for k, v in cfg.items():
        if not D(str(v)).is_finite():
            raise ValueError(f'Invalid setting {k}')
    if cfg['min_spend'] <= 0 or cfg['min_purchases'] < 1 or cfg['maturity_days'] < 0 or cfg['kill_romi'] >= cfg['scale_romi']:
        raise ValueError('Invalid decision thresholds')
    cutoff = as_of - timedelta(days=cfg['maturity_days'])
    groups = defaultdict(list)
    for key in sorted(ads.keys() | analytics.keys()):
        day = date.fromisoformat(key[0])
        if start <= day <= end:
            groups[key[1:]].append((day, ads.get(key), analytics.get(key)))
    if not groups:
        raise ValueError('No rows in selected date window')
    results, issues = [], []
    for (ad_id, country, currency), entries in sorted(groups.items()):
        sums = {k: D(0) for k in ('spend', 'impressions', 'clicks', 'purchases', 'net_revenue', 'variable_costs')}
        missing = False
        for day, a, b in entries:
            if a is None or b is None:
                missing = True
                issues.append(dict(date=str(day), ad_id=ad_id, country=country, currency=currency,
                                   issue='Missing ads row' if a is None else 'Missing analytics row'))
            for source in (a, b):
                if source:
                    for k in sums:
                        sums[k] += source.get(k, 0)
        spend = sums['spend']
        gp = sums['net_revenue'] - sums['variable_costs']
        egp = gp - spend
        romi = ratio(egp, spend, 100)
        status, reason = 'HOLD', 'Достатньо даних, але пороги kill/scale не досягнуті.'
        if missing:
            status, reason = 'DATA_ISSUE', 'Є непарні рядки. KPI результативності не розраховано.'
        elif any(day > cutoff for day, _, _ in entries):
            status, reason = 'WAIT', 'Вікно містить незрілі дані; дочекайтеся завершення атрибуції.'
        elif spend < D(str(cfg['min_spend'])):
            status, reason = 'WAIT', 'Витрати нижчі за мінімум для рішення.'
        elif romi is not None and romi < D(str(cfg['kill_romi'])):
            status, reason = 'KILL_REVIEW', 'ROMI нижчий за поріг; перевірте перед зупинкою.'
        elif romi is not None and romi >= D(str(cfg['scale_romi'])) and sums['purchases'] >= cfg['min_purchases']:
            status, reason = 'SCALE_REVIEW', 'ROMI та кількість покупок досягли порогів; перевірте можливість масштабування.'
        elif sums['purchases'] < cfg['min_purchases']:
            status, reason = 'WAIT', 'Замало покупок для кандидата на масштабування.'
        results.append(dict(ad_id=ad_id, country=country, currency=currency, **sums,
                            gross_profit=None if missing else gp,
                            egp=None if missing else egp, romi_pct=None if missing else romi,
                            cpa=None if missing else ratio(spend, sums['purchases']),
                            roas=None if missing else ratio(sums['net_revenue'], spend),
                            status=status, reason=reason))
    return results, issues, cfg


def display(v):
    if v is None:
        return '—'
    if isinstance(v, Decimal):
        return str(v.quantize(D('0.01')))
    return str(v)


def csv_cell(v):
    value = display(v)
    # Prevent text fields becoming spreadsheet formulas when exported.
    return "'" + value if isinstance(v, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value


def write_csv(path, rows, fields):
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: csv_cell(row.get(k)) for k in fields} for row in rows)


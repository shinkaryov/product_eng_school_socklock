"""Input normalization with explicit schema and locale contracts."""
import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path
from core import KEY, SCHEMAS, number

ALIASES = {
 'date': ['date','day','reporting starts','reporting_start','дата'],
 'ad_id': ['ad_id','ad id','advertisement_id','ідентифікатор оголошення'],
 'country': ['country','country_code','країна'],
 'currency': ['currency','currency_code','валюта'],
 'spend': ['spend','amount spent','amount spent (usd)','cost','витрати'],
 'impressions': ['impressions','покази'],
 'clicks': ['clicks','link clicks','кліки'],
 'purchases': ['purchases','orders','purchase_count','покупки'],
 'net_revenue': ['net_revenue','net revenue','net_sales','чистий виторг'],
 'variable_costs': ['variable_costs','variable costs','cogs_and_fees','змінні витрати'],
}


def norm(s):
    return re.sub(r'\s+',' ',str(s).strip().lower().replace('_',' '))


def read_rows(path):
    p=Path(path)
    if p.stat().st_size > 50*1024*1024:
        raise ValueError(f'{p}: file exceeds 50 MiB limit')
    text=p.read_text(encoding='utf-8-sig')
    if p.suffix.lower() in ('.csv','.tsv'):
        try:
            delimiter='\t' if p.suffix.lower()=='.tsv' else csv.Sniffer().sniff(text[:16384],delimiters=',;\t').delimiter
        except csv.Error:
            delimiter=','
        reader=csv.DictReader(io.StringIO(text),delimiter=delimiter)
        headers=reader.fieldnames or []
        if len(headers)!=len(set(headers)):
            raise ValueError(f'{p}: duplicate headers')
        rows=list(reader)
        if any(None in r or any(v is None for v in r.values()) for r in rows):
            raise ValueError(f'{p}: row width differs from header')
    elif p.suffix.lower()=='.json':
        def unique(pairs):
            result={}
            for k,v in pairs:
                if k in result: raise ValueError(f'Duplicate JSON key: {k}')
                result[k]=v
            return result
        rows=json.loads(text,object_pairs_hook=unique)
        if not isinstance(rows,list): raise ValueError('JSON must contain an array of row objects')
        headers=list(rows[0]) if rows and isinstance(rows[0],dict) else []
    elif p.suffix.lower() in ('.jsonl','.ndjson'):
        rows=[]
        for line,raw in enumerate(text.splitlines(),1):
            if raw.strip():
                try:
                    def unique_line(pairs):
                        d={}
                        for k,v in pairs:
                            if k in d: raise ValueError(f'Duplicate JSON key: {k}')
                            d[k]=v
                        return d
                    rows.append(json.loads(raw,object_pairs_hook=unique_line))
                except ValueError as e: raise ValueError(f'{p}: JSONL line {line}: {e}') from None
        headers=list(rows[0]) if rows and isinstance(rows[0],dict) else []
    else:
        raise ValueError('Supported formats: CSV, TSV, JSON array, JSONL/NDJSON')
    if not rows: raise ValueError(f'{p}: no data rows')
    if len(rows)>250000: raise ValueError(f'{p}: more than 250,000 rows')
    if any(not isinstance(r,dict) or set(r)!=set(headers) for r in rows):
        raise ValueError(f'{p}: inconsistent record schema')
    return headers,rows


def parse_number(value,field,decimal_separator):
    if isinstance(value,bool) or value is None:
        raise ValueError(f'{field}: null or boolean is not a number')
    if isinstance(value,str):
        value=value.strip().replace('\u00a0','').replace('\u202f','').replace(' ','')
        if decimal_separator==',':
            if '.' in value: raise ValueError(f'{field}: dot not allowed with decimal comma; omit thousands separators')
            value=value.replace(',','.')
        elif ',' in value:
            raise ValueError(f'{field}: ambiguous comma; select decimal_separator="," if decimal comma is intended')
    n=number(value,field)
    if n>10**12 or n.as_tuple().exponent < -6:
        raise ValueError(f'{field}: exceeds numeric limits (1e12, 6 decimal places)')
    return n


def load(path,kind,options=None):
    options=options or {}
    unknown=set(options)-{'columns','decimal_separator','date_format'}
    if unknown: raise ValueError(f'Unknown input options: {sorted(unknown)}')
    decimal=options.get('decimal_separator','.')
    if decimal not in ('.',','): raise ValueError('decimal_separator must be . or ,')
    headers,raw_rows=read_rows(path)
    explicit=options.get('columns',{})
    if set(explicit)-set(SCHEMAS[kind]): raise ValueError('Unknown canonical column in mapping')
    mapping={}
    for field in SCHEMAS[kind]:
        matches=[h for h in headers if norm(h) in {norm(a) for a in ALIASES[field]}]
        if field in explicit:
            matches=[explicit[field]] if explicit[field] in headers else []
        if len(matches)!=1:
            raise ValueError(f'{path}: {field}: expected one source column, found {matches}; set columns mapping')
        mapping[field]=matches[0]
    if len(set(mapping.values()))!=len(mapping): raise ValueError('One source column cannot map to multiple fields')
    result={}
    for index,raw in enumerate(raw_rows,2):
        try:
            row={k:raw[source] for k,source in mapping.items()}
            for k in KEY:
                if row[k] is None or isinstance(row[k],bool): raise ValueError(f'{k}: invalid key')
                if isinstance(row[k],(float,int)):
                    # JSON numeric IDs above JS safe range may already be corrupted upstream.
                    if k!='ad_id' or isinstance(row[k],float) or abs(row[k])>2**53-1:
                        raise ValueError(f'{k}: use a text value, especially for long IDs')
                row[k]=str(row[k]).strip()
                if not row[k] or len(row[k])>256 or any(ord(c)<32 for c in row[k]): raise ValueError(f'{k}: empty, too long or control characters')
            parsed=datetime.strptime(row['date'],options.get('date_format','%Y-%m-%d')).date()
            for h,v in raw.items():
                if norm(h) in ('reporting ends','end date','date stop'):
                    end_date=datetime.strptime(str(v).strip(),options.get('date_format','%Y-%m-%d')).date()
                    if end_date!=parsed: raise ValueError('Multi-day aggregate row; export daily data')
            row['date']=parsed.isoformat()
            row['country']=row['country'].upper();row['currency']=row['currency'].upper()
            if not re.fullmatch('[A-Z]{2}',row['country']): raise ValueError('country must be two ASCII letters')
            if not re.fullmatch('[A-Z]{3}',row['currency']): raise ValueError('currency must be three ASCII letters')
            for k in SCHEMAS[kind][4:]: row[k]=parse_number(row[k],k,decimal)
            if kind=='ads' and row['clicks']>row['impressions']: raise ValueError('clicks exceed impressions')
            if kind=='ads' and row['spend']>0 and row['impressions']==0: raise ValueError('positive spend with zero impressions')
            if kind=='analytics' and row['purchases']==0 and (row['net_revenue'] or row['variable_costs']): raise ValueError('zero purchases with revenue/costs: check accounting grain')
            if mapping.get('spend','').lower()=='amount spent (usd)' and row['currency']!='USD': raise ValueError('USD spend header conflicts with row currency')
            key=tuple(row[k] for k in KEY)
            if key in result: raise ValueError(f'duplicate key: {key}; aggregate breakdowns explicitly')
            result[key]=row
        except (ValueError,TypeError) as e:
            raise ValueError(f'{path}, record {index}: {e}') from None
    return result,{'file':str(path),'format':Path(path).suffix.lower(),'rows':len(result),'mapping':mapping,'options':options}

"""Self-contained HTML report and machine-readable exports."""
import json
from decimal import Decimal
from pathlib import Path
from core import write_csv


def serial(value):
    if isinstance(value,Decimal): return float(value)
    raise TypeError(type(value).__name__)


def write_reports(out,rows,issues,daily,metadata):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'report.csv',rows,list(rows[0]))
    write_csv(out/'issues.csv',issues,['date','ad_id','country','currency','severity','period','issue'])
    write_csv(out/'daily.csv',daily,list(daily[0]))
    (out/'audit.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2,default=serial),encoding='utf-8')
    payload=json.dumps(dict(rows=rows,issues=issues,daily=daily,meta=metadata),ensure_ascii=False,default=serial,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    (out/'report.json').write_text(payload,encoding='utf-8')
    template=Path(__file__).with_name('template.html').read_text(encoding='utf-8')
    (out/'report.html').write_text(template.replace('__REPORT_DATA__',payload),encoding='utf-8')

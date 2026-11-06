#!/usr/bin/env python3
"""UA Insight: normalize offline advertising exports and generate an actionable report."""
import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from ingest import load
from insights import build
from report import write_reports
from core import DEFAULTS


def run(args):
    cfg=json.loads(Path(args.config).read_text(encoding='utf-8')) if args.config else {}
    if not isinstance(cfg,dict) or set(cfg)-{'inputs','analysis'}: raise ValueError('Config accepts only inputs and analysis objects')
    inputs=cfg.get('inputs',{})
    if set(inputs)-{'ads','analytics'}: raise ValueError('Unknown input source in config')
    analysis=cfg.get('analysis',{})
    for threshold in [analysis.get('thresholds',{}),*analysis.get('currencies',{}).values()]:
        if set(threshold)-set(DEFAULTS): raise ValueError('Unknown decision threshold')
        for key in ('maturity_days','min_purchases'):
            if key in threshold and (isinstance(threshold[key],bool) or not isinstance(threshold[key],int)): raise ValueError(f'{key} must be integer')
    ads,am=load(args.ads,'ads',inputs.get('ads'))
    analytics,bm=load(args.analytics,'analytics',inputs.get('analytics'))
    rows,issues,daily,periods=build(ads,analytics,date.fromisoformat(args.start),date.fromisoformat(args.end),date.fromisoformat(args.as_of),analysis)
    for record in (am,bm): record['sha256']=hashlib.sha256(Path(record['file']).read_bytes()).hexdigest()
    metadata=dict(version='2.0',**periods,as_of=args.as_of,sources=[am,bm],config=cfg,
                  defaults=DEFAULTS,assumptions='Same timezone, daily grain and attribution model; explicit zero rows; no FX conversion. Baseline is previous equal-length window.')
    write_reports(args.out,rows,issues,daily,metadata)
    print(f'OK: {len(rows)} groups; {len(issues)} quality messages; {Path(args.out)/"report.html"}')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('ads','analytics','start','end','as-of'): p.add_argument('--'+name,required=True)
    p.add_argument('--config',help='Optional JSON column mappings and analysis thresholds')
    p.add_argument('--out',default='output')
    args=p.parse_args()
    try:
        run(args);return 0
    except (ValueError,OSError,TypeError,KeyError,AttributeError,OverflowError) as e:
        print(f'ERROR: {e}',file=sys.stderr);return 2


if __name__=='__main__': sys.exit(main())

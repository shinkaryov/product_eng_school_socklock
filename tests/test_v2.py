import argparse,csv,json,sys,tempfile,unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from generate_demo import generate
from ingest import load,parse_number
from insights import build
from report import write_reports
from ua_report import run


class ExtendedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.p=Path(self.tmp.name);generate(self.p)
        self.a=load(self.p/'ads.csv','ads')[0];self.b=load(self.p/'analytics.csv','analytics')[0]
    def report(self,config=None):
        return build(self.a,self.b,date(2026,10,26),date(2026,11,1),date(2026,11,5),config or {})
    def test_four_formats_equal(self):
        for kind in ['ads','analytics']:
            expected=load(self.p/f'{kind}.csv',kind)[0]
            for ext in ['tsv','json','jsonl']:
                with self.subTest(kind=kind,ext=ext): self.assertEqual(load(self.p/f'{kind}.{ext}',kind)[0],expected)
    def test_alias_decimal_comma(self):
        actual,meta=load(self.p/'ads_meta.csv','ads',{'decimal_separator':','})
        self.assertEqual(actual,self.a);self.assertEqual(meta['mapping']['spend'],'Amount spent')
    def test_unknown_and_ambiguous_columns(self):
        data=json.loads((self.p/'ads.json').read_text());data[0]['cost']=100
        # Make schema consistent, but alias ambiguous.
        for r in data:r['cost']=r['spend']
        (self.p/'bad.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'expected one source column'):load(self.p/'bad.json','ads')
        result,_=load(self.p/'bad.json','ads',{'columns':{'spend':'spend'}})
        self.assertEqual(result,self.a)
    def test_no_silent_gross_to_net_mapping(self):
        data=json.loads((self.p/'analytics.json').read_text())
        for r in data:r['revenue']=r.pop('net_revenue')
        (self.p/'bad.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'net_revenue'):load(self.p/'bad.json','analytics')
    def test_invalid_numbers(self):
        for val in [True,None,'NaN','Infinity','1e99','0.00000001','-1','1,000']:
            with self.subTest(value=val),self.assertRaises(ValueError):parse_number(val,'spend','.')
        self.assertEqual(parse_number('1 234,50','spend',','),D('1234.50'))
    def test_schema_shape_and_duplicate_headers(self):
        for filename,content in [('bad.csv','date,date\nx,x\n'),('bad.json','{}'),('bad.jsonl','{}\n[]')]:
            (self.p/filename).write_text(content)
            with self.assertRaises(ValueError):load(self.p/filename,'ads')
    def test_numeric_long_id(self):
        rows=json.loads((self.p/'ads.json').read_text());rows[0]['ad_id']=999999999999999999
        (self.p/'bad.json').write_text(json.dumps(rows))
        with self.assertRaisesRegex(ValueError,'long IDs'):load(self.p/'bad.json','ads')
    def test_date_format_explicit(self):
        rows=json.loads((self.p/'ads.json').read_text())
        for r in rows:r['date']=date.fromisoformat(r['date']).strftime('%d/%m/%Y')
        (self.p/'dated.json').write_text(json.dumps(rows))
        with self.assertRaises(ValueError):load(self.p/'dated.json','ads')
        self.assertEqual(load(self.p/'dated.json','ads',{'date_format':'%d/%m/%Y'})[0],self.a)
    def test_trend_overrides_scale(self):
        rows,_,_,_=self.report();r=next(r for r in rows if r['ad_id']=='declining')
        self.assertEqual(r['status'],'DECLINE_REVIEW')
        self.assertEqual(r['romi_change_pp'],-220)
        self.assertIn('CTR',r['diagnosis'])
        self.assertEqual(r['previous_egp'],2100)
    def test_missing_baseline_not_imputed(self):
        self.a={k:v for k,v in self.a.items() if k[0]>='2026-10-26'}
        self.b={k:v for k,v in self.b.items() if k[0]>='2026-10-26'}
        rows,_,_,_=self.report()
        self.assertTrue(all(not r['comparison_available'] for r in rows))
        self.assertTrue(all(r['romi_change_pp'] is None for r in rows))
    def test_sparse_current_blocks_scale(self):
        for source in (self.a,self.b):
            for k in list(source):
                if k[1]=='steady_winner' and k[0]=='2026-10-27':del source[k]
        rows,issues,_,_=self.report();r=next(r for r in rows if r['ad_id']=='steady_winner')
        self.assertEqual(r['status'],'WAIT');self.assertFalse(r['comparison_available'])
        self.assertTrue(any(i['severity']=='warning' for i in issues))
    def test_missing_join_blocks_financials(self):
        rows,issues,_,_=self.report();r=next(r for r in rows if r['ad_id']=='tracking_gap')
        self.assertEqual(r['status'],'DATA_ISSUE');self.assertIsNone(r['egp']);self.assertEqual(len(issues),1)
    def test_unmatured_never_kill(self):
        rows,_,_,_=build(self.a,self.b,date(2026,10,26),date(2026,11,1),date(2026,11,2),{})
        self.assertFalse(any(r['status'] in ['KILL_REVIEW','SCALE_REVIEW','DECLINE_REVIEW'] for r in rows))
    def test_currency_specific_threshold(self):
        rows,_,_,_=self.report({'currencies':{'EUR':{'min_spend':10000}}})
        self.assertEqual(next(r for r in rows if r['currency']=='EUR')['status'],'WAIT')
    def test_daily_reconciles(self):
        rows,_,daily,_=self.report()
        for currency in ['USD','EUR']:
            current=[r for r in rows if r['currency']==currency and r['egp'] is not None]
            dd=[r for r in daily if r['currency']==currency and r['period']=='current']
            self.assertEqual(sum(r['egp'] for r in current),sum(r['egp'] or 0 for r in dd))
    def test_future_dates_rejected(self):
        with self.assertRaisesRegex(ValueError,'future'):build(self.a,self.b,date(2026,10,26),date(2026,10,29),date(2026,10,30),{})
    def test_safe_html_payload_and_csv(self):
        rows,issues,daily,meta=self.report();rows[0]['ad_id']='</script><script>alert(1)</script>'
        rows[1]['ad_id']='=1+1';write_reports(self.p/'out',rows,issues,daily,meta)
        page=(self.p/'out/report.html').read_text()
        self.assertNotIn('</script><script>alert(1)',page)
        self.assertIn('\\u003c/script',page)
        with (self.p/'out/report.csv').open(encoding='utf-8-sig') as f:
            exported=list(csv.DictReader(f));self.assertEqual(exported[1]['ad_id'],"'=1+1")
    def test_duplicate_jsonl_key(self):
        (self.p/'bad.jsonl').write_text('{"date":"2026-01-01","date":"2026-01-02"}')
        with self.assertRaisesRegex(ValueError,'Duplicate JSON key'):load(self.p/'bad.jsonl','ads')
    def test_aggregated_date_range_rejected(self):
        data=json.loads((self.p/'ads.json').read_text())
        for r in data:r['Reporting ends']='2026-11-01'
        (self.p/'bad.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'Multi-day'):load(self.p/'bad.json','ads')
    def test_zero_purchases_revenue_rejected(self):
        data=json.loads((self.p/'analytics.json').read_text());data[0]['purchases']=0
        (self.p/'bad.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'zero purchases'):load(self.p/'bad.json','analytics')
    def test_small_baseline_no_trend(self):
        for k,v in self.a.items():
            if k[0]<'2026-10-26':v['spend']=D('0.1')
        rows,_,_,_=self.report()
        self.assertTrue(all(not r['comparison_available'] for r in rows))
    def test_cli_config_and_output(self):
        args=argparse.Namespace(ads=str(self.p/'ads.tsv'),analytics=str(self.p/'analytics.json'),start='2026-10-26',end='2026-11-01',as_of='2026-11-05',out=str(self.p/'out'),config=None)
        run(args)
        self.assertEqual(set(p.name for p in (self.p/'out').iterdir()),{'report.html','report.csv','report.json','daily.csv','issues.csv','audit.json'})
        audit=json.loads((self.p/'out/audit.json').read_text());self.assertEqual(len(audit['sources'][0]['sha256']),64)

if __name__=='__main__':unittest.main()

import csv
import random
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core as ua
from legacy_demo import generate


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        generate(self.root)
        self.ads = ua.load(self.root/'ads.csv','ads')
        self.analytics = ua.load(self.root/'analytics.csv','analytics')

    def report(self, config=None):
        return ua.analyze(self.ads,self.analytics,date(2026,10,28),date(2026,11,3),date(2026,11,4),config or {})

    def test_hand_calculated_financials(self):
        rows, _, _ = self.report()
        r = next(r for r in rows if r['ad_id']=='winner')
        self.assertEqual(r['spend'],300)
        self.assertEqual(r['egp'],660)
        self.assertEqual(r['romi_pct'],220)
        self.assertEqual(r['cpa'],5)
        self.assertEqual(r['roas'],4)

    def test_all_decision_branches(self):
        rows, issues, _ = self.report()
        actual = {r['ad_id']:r['status'] for r in rows}
        self.assertEqual(actual, dict(winner='SCALE_REVIEW',loser='KILL_REVIEW',no_sales='KILL_REVIEW',small_sample='WAIT',hold='HOLD',tracking_gap='DATA_ISSUE',zero_spend='WAIT',new_ad='WAIT',winner_eu='SCALE_REVIEW',unmatched_backend='DATA_ISSUE'))
        self.assertEqual(len(issues),2)

    def test_missing_is_not_zero(self):
        rows, _, _ = self.report()
        for r in rows:
            if r['status']=='DATA_ISSUE':
                self.assertIsNone(r['egp'])
                self.assertIsNone(r['romi_pct'])

    def test_zero_denominator(self):
        rows, _, _ = self.report()
        r = next(r for r in rows if r['ad_id']=='zero_spend')
        self.assertIsNone(r['romi_pct'])
        self.assertIsNone(r['roas'])
        r = next(r for r in rows if r['ad_id']=='no_sales')
        self.assertIsNone(r['cpa'])

    def test_duplicate_fails(self):
        p = self.root/'ads.csv'
        with p.open('a') as f:
            f.write(p.read_text().splitlines()[1]+'\n')
        with self.assertRaisesRegex(ValueError,'duplicate key'):
            ua.load(p,'ads')

    def test_bad_numeric_inputs(self):
        for value in ['NaN','Infinity','-1','not-a-number','1,000']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ua.number(value,'spend')
        with self.assertRaises(ValueError):
            ua.number('1.5','purchases')

    def test_schema_and_empty_file(self):
        for content in ['date,ad_id\n','', 'date,date\n']:
            (self.root/'bad.csv').write_text(content)
            with self.assertRaises(ValueError):
                ua.load(self.root/'bad.csv','ads')

    def test_invalid_date_and_clicks(self):
        p = self.root/'ads.csv'
        for row in ['2026-02-30,a,US,USD,1,2,1','2026-01-01,a,US,USD,1,1,2','2026-01-01,,US,USD,1,2,1']:
            p.write_text(','.join(ua.SCHEMAS['ads'])+'\n'+row+'\n')
            with self.assertRaises(ValueError):
                ua.load(p,'ads')

    def test_window_and_threshold_validation(self):
        with self.assertRaises(ValueError):
            ua.analyze(self.ads,self.analytics,date(2027,1,1),date(2026,1,1),date(2026,2,1),{})
        for cfg in [{'min_spend':0},{'kill_romi':30,'scale_romi':25},{'min_spend':D('NaN')}]:
            with self.assertRaises(ValueError):
                self.report(cfg)

    def test_maturity_boundary(self):
        rows,_,_ = ua.analyze(self.ads,self.analytics,date(2026,10,28),date(2026,10,30),date(2026,11,2),{})
        self.assertEqual(next(r for r in rows if r['ad_id']=='winner')['status'],'SCALE_REVIEW')

    def test_order_invariance(self):
        expected = self.report()[0]
        self.ads = dict(reversed(list(self.ads.items())))
        self.analytics = dict(reversed(list(self.analytics.items())))
        self.assertEqual(expected,self.report()[0])

    def test_generated_financial_invariants(self):
        rng = random.Random(42)
        for i in range(200):
            spend, revenue, costs = (D(rng.randint(1,100000))/100 for _ in range(3))
            key = ('2026-10-30',str(i),'US','USD')
            a = dict(zip(ua.KEY,key),spend=spend,impressions=D(100),clicks=D(10))
            b = dict(zip(ua.KEY,key),purchases=D(10),net_revenue=revenue,variable_costs=costs)
            rows,_,_=ua.analyze({key:a},{key:b},date(2026,10,30),date(2026,10,30),date(2026,11,4),{})
            r=rows[0]
            self.assertEqual(r['egp']+spend+costs,revenue)
            self.assertEqual(r['romi_pct'],(revenue-costs-spend)/spend*100)



if __name__ == '__main__':
    unittest.main()

"""Deterministic synthetic fixtures; no production data."""
import csv
from pathlib import Path


def generate(destination):
    destination.mkdir(parents=True, exist_ok=True)
    ads, analytics = [], []
    cases = [('winner',100,20,400,80), ('loser',180,3,90,30),
             ('no_sales',140,0,0,0), ('small_sample',20,1,40,10),
             ('hold',100,12,150,40), ('tracking_gap',90,5,120,30),
             ('zero_spend',0,2,60,10)]
    for day in ('2026-10-28','2026-10-29','2026-10-30'):
        for name, spend, purchases, revenue, costs in cases:
            key = [day,name,'US','USD']
            ads.append(key + [spend,10000,200])
            if not (name == 'tracking_gap' and day == '2026-10-29'):
                analytics.append(key + [purchases,revenue,costs])
    ads.append(['2026-11-03','new_ad','US','USD',150,10000,200])
    analytics.append(['2026-11-03','new_ad','US','USD',15,400,70])
    ads.append(['2026-10-30','winner_eu','FR','EUR',120,10000,200])
    analytics.append(['2026-10-30','winner_eu','FR','EUR',15,360,100])
    analytics.append(['2026-10-30','unmatched_backend','US','USD',4,100,20])
    for name, fields, rows in [('ads', ['spend','impressions','clicks'], ads), ('analytics',['purchases','net_revenue','variable_costs'], analytics)]:
        with open(destination / (name + '.csv'), 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(['date','ad_id','country','currency'] + fields)
            w.writerows(rows)
    return ads, analytics


if __name__ == '__main__':
    generate(Path(__file__).parent / 'demo')
    print('Synthetic fixtures generated in demo/')

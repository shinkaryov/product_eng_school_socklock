"""Generate reproducible synthetic exports in four formats."""
import csv,json
from datetime import date,timedelta
from pathlib import Path
from core import KEY


def generate(destination):
    destination.mkdir(parents=True,exist_ok=True)
    ads=[];analytics=[]
    cases=[('steady_winner',100,20,400,80),('loser',180,3,90,30),('no_sales',140,0,0,0),('small_sample',3,1,20,5),('hold',100,12,150,40),('tracking_gap',90,5,120,30),('declining',100,25,500,100)]
    for i in range(14):
        day=str(date(2026,10,19)+timedelta(days=i))
        for name,spend,purchases,revenue,costs in cases:
            impressions,clicks=10000,200
            if name=='declining' and i>=7: purchases,revenue,costs,clicks=12,240,60,100
            if name=='steady_winner': revenue+=i*3
            a=dict(zip(KEY,[day,name,'US','USD']),spend=spend,impressions=impressions,clicks=clicks)
            b=dict(zip(KEY,[day,name,'US','USD']),purchases=purchases,net_revenue=revenue,variable_costs=costs)
            ads.append(a)
            if not(name=='tracking_gap' and i==10): analytics.append(b)
        ads.append(dict(zip(KEY,[day,'europe_winner','FR','EUR']),spend=80,impressions=9000,clicks=180))
        analytics.append(dict(zip(KEY,[day,'europe_winner','FR','EUR']),purchases=15,net_revenue=300,variable_costs=70))
    for name,rows in [('ads',ads),('analytics',analytics)]:
        for ext,delimiter in [('csv',','),('tsv','\t')]:
            with (destination/f'{name}.{ext}').open('w',encoding='utf-8',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]),delimiter=delimiter);w.writeheader();w.writerows(rows)
        (destination/f'{name}.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
        (destination/f'{name}.jsonl').write_text('\n'.join(json.dumps(r) for r in rows),encoding='utf-8')
    with (destination/'ads_meta.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f,delimiter=';');w.writerow(['Reporting starts','Ad ID','Country','Currency','Amount spent','Impressions','Link clicks'])
        for r in ads:w.writerow([r['date'],r['ad_id'],r['country'],r['currency'],f"{r['spend']:.2f}".replace('.',','),r['impressions'],r['clicks']])
    return ads,analytics


if __name__=='__main__': generate(Path(__file__).parent/'demo')

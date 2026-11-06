"""Period comparisons and evidence-based review queue; no automatic ad changes."""
from collections import defaultdict
from datetime import date,timedelta
from decimal import Decimal as D
from core import analyze,ratio,display


def enrich(r):
    complete=r['egp'] is not None
    r['ctr_pct']=ratio(r['clicks'],r['impressions'],100)
    r['cpc']=ratio(r['spend'],r['clicks'])
    r['cpm']=ratio(r['spend'],r['impressions'],1000)
    r['cvr_pct']=ratio(r['purchases'],r['clicks'],100) if complete else None
    r['aov']=ratio(r['net_revenue'],r['purchases']) if complete else None
    return r


def change(current,previous):
    return (current/previous-1)*100 if current is not None and previous is not None and previous>0 else None


def build(ads,analytics,start,end,as_of,config):
    allowed={'thresholds','currencies','min_days','min_impressions','min_clicks','min_coverage','trend_drop_pp'}
    if set(config)-allowed: raise ValueError(f'Unknown analysis options: {set(config)-allowed}')
    min_days=config.get('min_days',3)
    min_impressions=config.get('min_impressions',1000)
    min_clicks=config.get('min_clicks',30)
    min_coverage=D(str(config.get('min_coverage',1)))
    drop=D(str(config.get('trend_drop_pp',20)))
    if any(isinstance(v,bool) or not isinstance(v,int) or v<1 for v in (min_days,min_impressions,min_clicks)) or not min_coverage.is_finite() or not 0<min_coverage<=1 or not drop.is_finite() or drop<=0:
        raise ValueError('Invalid evidence thresholds')
    days=(end-start).days+1
    if days<1 or days>366: raise ValueError('Window must be 1–366 days')
    prev_end=start-timedelta(days=1);prev_start=start-timedelta(days=days)
    all_keys=ads.keys()|analytics.keys()
    if any(date.fromisoformat(k[0])>as_of for k in all_keys): raise ValueError('Input contains future dates relative to as-of')
    rows=[];issues=[];daily=[]
    currencies=sorted({k[3] for k in all_keys if prev_start<=date.fromisoformat(k[0])<=end})
    for currency in currencies:
        aa={k:v for k,v in ads.items() if k[3]==currency}
        bb={k:v for k,v in analytics.items() if k[3]==currency}
        if not any(start<=date.fromisoformat(k[0])<=end for k in aa.keys()|bb.keys()): continue
        cfg=dict(config.get('thresholds',{}),**config.get('currencies',{}).get(currency,{}))
        group_keys=defaultdict(list)
        date_keys=defaultdict(list)
        for k in aa.keys()|bb.keys():
            group_keys[k[1:3]].append(k)
            date_keys[k[0]].append(k)
        current,errors,used=analyze(aa,bb,start,end,as_of,cfg)
        for e in errors: issues.append(dict(e,period='current',severity='error'))
        previous={}
        if any(prev_start<=date.fromisoformat(k[0])<=prev_end for k in aa.keys()|bb.keys()):
            pp,ee,_=analyze(aa,bb,prev_start,prev_end,as_of,cfg)
            previous={(r['ad_id'],r['country']):enrich(r) for r in pp}
            for e in ee: issues.append(dict(e,period='previous',severity='error'))
        for r in current:
            enrich(r)
            key=(r['ad_id'],r['country'])
            keys=[k for k in group_keys[key] if start<=date.fromisoformat(k[0])<=end]
            matched=sum(k in aa and k in bb for k in keys)
            observed=len(keys)
            r['observed_days']=observed;r['matched_days']=matched
            r['coverage_pct']=D(matched)/days*100
            prev=previous.get(key)
            prev_keys=[k for k in group_keys[key] if prev_start<=date.fromisoformat(k[0])<=prev_end]
            prev_matched=sum(k in aa and k in bb for k in prev_keys)
            comparable=bool(prev and prev['spend']>=D(str(used['min_spend'])) and r['spend']>=D(str(used['min_spend'])) and prev['egp'] is not None and r['egp'] is not None and D(matched)/days>=min_coverage and D(prev_matched)/days>=min_coverage)
            r['comparison_available']=comparable
            r['previous_egp']=prev['egp'] if comparable else None
            r['previous_romi_pct']=prev['romi_pct'] if comparable else None
            r['romi_change_pp']=r['romi_pct']-prev['romi_pct'] if comparable and r['romi_pct'] is not None and prev['romi_pct'] is not None else None
            for metric in ('cpa','ctr_pct','cvr_pct','cpm','aov','spend'):
                r[metric+'_change_pct']=change(r[metric],prev[metric]) if comparable else None
            evidence=[]
            if r['egp'] is not None:
                evidence.append(f"EGP {display(r['egp'])} {currency}; ROMI {display(r['romi_pct'])}%; spend {display(r['spend'])}.")
            if observed<days:
                evidence.append(f'{observed}/{days} днів присутні: можливий неповний експорт або нове/неактивне оголошення.')
                issues.append(dict(date='',ad_id=r['ad_id'],country=r['country'],currency=currency,issue=f'Only {observed}/{days} current days present; activity unknown',period='current',severity='warning'))
            enough=matched>=min_days and D(matched)/days>=min_coverage
            if r['status'] in ('KILL_REVIEW','SCALE_REVIEW','HOLD') and not enough:
                r['status']='WAIT';r['reason']='Недостатнє покриття періоду або кількість зрілих днів.'
            if r['status']=='SCALE_REVIEW' and (r['impressions']<min_impressions or r['clicks']<min_clicks):
                r['status']='WAIT';r['reason']='Замало показів або кліків для масштабування.'
            if comparable:
                evidence.append(f"ROMI Δ {display(r['romi_change_pp'])} п.п.; CPA Δ {display(r['cpa_change_pct'])}%; CTR Δ {display(r['ctr_pct_change_pct'])}%.")
            else:
                evidence.append('Немає достатньо повної бази для порівняння періодів; тренд не визначено.')
            trend=r['romi_change_pp']
            worsening=trend is not None and trend<=-drop
            # Trend diagnosis only on eligible mature records, never overriding data gates.
            if worsening and r['status'] in ('HOLD','SCALE_REVIEW'):
                r['status']='DECLINE_REVIEW';r['reason']='ROMI суттєво знизився проти попереднього періоду; перевірити до масштабування.'
            diagnostic=[]
            if comparable and r['clicks']>=min_clicks and prev['clicks']>=min_clicks and r['impressions']>=min_impressions and prev['impressions']>=min_impressions:
                if r['ctr_pct_change_pct'] is not None and r['ctr_pct_change_pct']<=-20: diagnostic.append('CTR знизився ≥20%: перевірити креатив і аудиторію; це не доказ creative fatigue.')
                if r['cvr_pct_change_pct'] is not None and r['cvr_pct_change_pct']<=-20: diagnostic.append('Конверсія click→purchase знизилась ≥20%: перевірити воронку та атрибуцію.')
                if r['cpm_change_pct'] is not None and r['cpm_change_pct']>=20: diagnostic.append('CPM зріс ≥20%: перевірити вартість аукціону й аудиторію.')
            if r['purchases']>r['clicks']:
                diagnostic.append('Покупок більше за кліки: перевірити view-through і multi-purchase атрибуцію.')
                if r['status']!='DATA_ISSUE':
                    r['status']='ATTRIBUTION_REVIEW';r['reason']='Покупки перевищують кліки; спочатку перевірити модель атрибуції.'
            r['evidence']=' '.join(evidence)
            r['diagnosis']=' '.join(diagnostic) or 'Окремого діагностичного сигналу немає.'
            r['priority_amount']=max(D(0),-r['egp']) if r['status']=='KILL_REVIEW' else r['spend']
            r['priority_basis']='Observed loss' if r['status']=='KILL_REVIEW' else 'Affected spend'
            r['next_action']={
                'KILL_REVIEW':'Перевірити атрибуцію й маржу; розглянути зупинку або зменшення бюджету.',
                'SCALE_REVIEW':'Перевірити ліміти й протестувати мале підвищення бюджету; порівняти маржинальний ROMI.',
                'DECLINE_REVIEW':'Розібрати зміни CTR, CVR і CPM; відкласти масштабування до перевірки.',
                'DATA_ISSUE':'Виправити непарні записи та повторно сформувати звіт.',
                'ATTRIBUTION_REVIEW':'Узгодити click/view-through атрибуцію перед рішенням.',
                'WAIT':'Дочекатися зрілості або доповнити вибірку; повторити аналіз.',
                'HOLD':'Залишити під спостереженням до наступного зрілого періоду.',
            }[r['status']]
            rows.append(r)
        # Chart totals use a fixed cohort of complete current groups across both periods.
        cohort={(r['ad_id'],r['country']) for r in current if r['egp'] is not None}
        for offset in range(days*2):
            day=prev_start+timedelta(days=offset)
            kk=[k for k in date_keys[str(day)] if k[1:3] in cohort]
            spend=sum((aa[k]['spend'] for k in kk if k in aa and k in bb),D(0))
            gp=sum((bb[k]['net_revenue']-bb[k]['variable_costs'] for k in kk if k in aa and k in bb),D(0))
            daily.append(dict(date=str(day),currency=currency,spend=spend if kk else None,egp=gp-spend if kk else None,matched_groups=sum(k in aa and k in bb for k in kk),expected_groups=len(cohort),period='current' if day>=start else 'previous'))
    if not rows: raise ValueError('No rows in selected window')
    order={'DATA_ISSUE':0,'ATTRIBUTION_REVIEW':1,'KILL_REVIEW':2,'DECLINE_REVIEW':3,'SCALE_REVIEW':4,'WAIT':5,'HOLD':6}
    rows.sort(key=lambda r:(r['currency'],order[r['status']],-r['priority_amount'],r['ad_id'],r['country']))
    return rows,issues,daily,dict(previous_start=str(prev_start),previous_end=str(prev_end),current_start=str(start),current_end=str(end))

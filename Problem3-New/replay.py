"""Independently reconcile executed power balance, SOC, trade ledger and tables."""
import json
from datetime import datetime,timedelta
import numpy as np
from forecast import OUT, ROOT, data_arrays
from check_inputs import read_xlsx, sha256


def label(t):
    return f'{t//6:02d}:{10*(t%6):02d}'


def validate(name):
    a=np.load(OUT/f'{name}.npz');data,load,pv,price=data_arrays()
    q,c,d,h,w,e=[a[k] for k in ['q','c','d','h','w','e']]
    n=len(q);days=len(a['q0']);p=price[np.arange(n)%144];net=(load[:n]-pv[:n])/6
    reconstructed=6000+np.r_[0,np.cumsum(.9*c-d/.9)]
    h2=np.maximum(0,net+c-d-q);w2=np.maximum(0,q+d-net-c)
    q0=a['q0'];qf=a['qfinal'];delta=a['delta']
    checks={'soc_reconstruction_kwh':float(np.abs(e-reconstructed).max()),
        'balance_kwh':float(np.abs(q+h+d-net-c-w).max()),
        'h_reconstruction_kwh':float(np.abs(h-h2).max()),'w_reconstruction_kwh':float(np.abs(w-w2).max()),
        'soc_bounds_kwh':float(max(0,1200-e.min(),e.max()-10800)),
        'power_kwh':float(max(0,(c+d).max()-5000/6)),
        'nonnegative_kwh':float(max(0,-min(q.min(),c.min(),d.min(),h.min(),w.min()))),
        'emergency_charging_count':int(((h>1e-6)&(c>1e-6)).sum()),
        'simultaneous_count':int(((c>1e-6)&(d>1e-6)).sum()),
        'plan_ledger_kwh':float(np.abs(q0+delta.sum(1)-qf).max()),
        'executed_plan_mapping_kwh':float(np.abs(q.reshape(days,144)-qf).max()),
        'lp_residual':float(a['lp_residual'])}
    for r in range(3):assert np.max(np.abs(delta[:,r,:(r+1)*36]),initial=0)<1e-7
    for day in range(days):
        for r in range(4):
            ids=a['scenario_ids'][day,r];ids=ids[ids>=0]
            assert np.all(ids*36+144<(day*4+r)*36)
    row_price=np.tile(data.price,(days,1))
    original=(q0*row_price).sum(1)
    incr=((1.5*np.maximum(delta,0)-.5*np.maximum(-delta,0))*row_price[:,None,:]).sum((1,2))
    trade=original+incr
    if any(v>1e-5 for v in checks.values()):raise AssertionError(checks)
    # All costs are evaluated on the natural calendar day.  The official
    # workbook headers are preserved verbatim, but they do not redefine the
    # interval-end convention of Attachments 1 and 2.
    start=31*144;end=days*144
    emergency_calendar=float((h[start:end]*5*p[start:end]).sum())
    cost_at=(q0*row_price+((1.5*np.maximum(delta,0)-.5*np.maximum(-delta,0))*row_price[:,None,:]).sum(1)).reshape(-1)
    cost_calendar=float(cost_at[start:end].sum())+emergency_calendar
    events=[];battery=[];paper=[]
    for day in range(31,days):
        excel_day=45658+day;startday=day*144;date=str(data.dates[day])
        for block in range(6):
            sl=slice(startday+block*24,startday+(block+1)*24)
            battery.append([excel_day if block==0 else None,f'{block*4}:00-{(block+1)*4}:00',
                float(c[sl].sum()),float(d[sl].sum()),0 if block==0 else ('24:00' if block==1 else None),
                float(e[startday]) if block==0 else (float(e[startday+144]) if block==1 else None)])
        daily_events=[];begin=None
        for t in range(145):
            active=t<144 and h[startday+t]>1e-6
            if active and begin is None:begin=t
            if not active and begin is not None:
                daily_events.append([None,label(begin)+'-'+label(t),float(h[startday+begin:startday+t].sum())]);begin=None
        if daily_events:
            daily_events[0][0]=excel_day
            events.extend(daily_events)
        if date in ['2025-03-20','2025-06-21','2025-09-23','2025-12-21']:
            paper.append({'date':date,'specified_q_kwh':{label(t):float(q[startday+t]) for t in [60,72,84,96,108,120]},
                'calendar_q_kwh':float(q[startday:startday+144].sum()),
                'calendar_cost_yuan':float((cost_at+5*p*h)[startday:startday+144].sum()),
                'soc0_kwh':float(e[startday]),'soc24_kwh':float(e[startday+144]),
                'emergency_events':daily_events})
    report={'variant':name,'days':days,'checks':checks,'initial_feb_soc_kwh':float(e[31*144]) if days>31 else None,
        'calendar_cost_yuan':cost_calendar,'template_cost_yuan':cost_calendar,
        'planned_cost_yuan':float(original[31:].sum()),'adjustment_net_cost_yuan':float(incr[31:].sum()),
        'calendar_emergency_cost_yuan':emergency_calendar,'template_emergency_cost_yuan':emergency_calendar,
        'calendar_emergency_kwh':float(h[31*144:days*144].sum()),
        'template_emergency_kwh':float(h[31*144:days*144].sum()),
        'terminal_midnight_soc_kwh':float(e[days*144]),'terminal_template_soc_kwh':float(e[-1]),
        'accepted_updates':{str(6*(r+1)):int((a['gains'][31:,r]>0).sum()) for r in range(3)},
        'paper_dates':paper,
        'source_hashes':{s:sha256(ROOT/'C题/附件'/s) for s in ['附件1.xlsx','附件2.xlsx','附件3.xlsx','附件5/result3.xlsx']}}
    if name=='main':
        tables={'plan':[[45658+day,*q0[day].tolist(),float(q0[day].sum()),float(original[day])] for day in range(31,days)],
                'adjusted':[[45658+day,*qf[day].tolist(),float(qf[day].sum()),float(trade[day])] for day in range(31,days)],
                'battery':battery,'emergency':events}
        (OUT/'tables.json').write_text(json.dumps(tables,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    return report


def main():
    result={}
    for name in ['main','only0','no6','no12','no18']:
        if (OUT/f'{name}.npz').exists():
            result[name]=validate(name)
            print(name,result[name]['calendar_cost_yuan'],result[name]['checks'],flush=True)
    (OUT/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def verify_workbook():
    original=read_xlsx(ROOT/'C题/附件/附件5/result3.xlsx')
    final=read_xlsx(OUT/'result3.xlsx')
    tables=json.loads((OUT/'tables.json').read_text(encoding='utf-8'))
    assert list(original)==list(final)
    for sheet,key in [('计划购电量','plan'),('调整购电量','adjusted'),('充放电量','battery'),('紧急购电量','emergency')]:
        assert original[sheet][0]==final[sheet][0]
        expected=tables[key];actual=final[sheet][1:]
        assert len(expected)==len(actual),(sheet,len(expected),len(actual))
        for r,(a,b) in enumerate(zip(expected,actual),2):
            assert len(a)==len(b)
            for col,(x,y) in enumerate(zip(a,b),1):
                if isinstance(x,(int,float)):
                    assert isinstance(y,(int,float)) and abs(x-y)<1e-7,(sheet,r,col,x,y)
                else:assert x==y,(sheet,r,col,x,y)
    # Verify model versions independently of their prediction archive.
    import torch
    for p in (OUT/'models').glob('*.pt'):
        model=torch.load(p,map_location='cpu',weights_only=False)
        assert model['train_max_target']<model['cutoff']-7*144
        assert model['validation_max_target']<model['cutoff']
    # Hand-worked sequential settlement check: 100 -> 80 -> 90 at price 1.
    changes=np.array([-20.,10.])
    assert 100+(1.5*np.maximum(changes,0)-.5*np.maximum(-changes,0)).sum()==105
    print('Workbook values, all original headers, model cutoff metadata and settlement example verified.')


if __name__=='__main__':main()

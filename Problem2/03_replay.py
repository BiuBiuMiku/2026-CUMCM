"""Independent physical reconstruction and settlement, without trusting stored h/E."""
import numpy as np
from common import *


def validate(q,c,d,actual_net_kw,stored_soc=None,stored_h=None):
    n=len(q)
    net=actual_net_kw[:n]*DT
    h=np.maximum(0,net+c-d-q)
    w=np.maximum(0,q+d-c-net)
    # Independently integrate ALL executed actions from the original initial state.
    trajectory=E_INITIAL+np.r_[0,np.cumsum((ETA*c-d/ETA).reshape(-1))]
    e=np.stack([trajectory[day*144:day*144+145] for day in range(n)])
    checks={'balance_kwh':float(np.max(np.abs(q+h+d-net-c-w))),
            'soc_bound_kwh':float(max(0,E_MIN-e.min(),e.max()-E_MAX)),
            'time_budget_kwh':float(max(0,(c+d).max()-U)),
            'negative_kwh':float(max(0,-min(q.min(),c.min(),d.min()))),
            'cross_day_kwh':float(np.max(np.abs(e[1:,0]-e[:-1,-1])) if n>1 else 0),
            'simultaneous_count':int(np.sum((c>1e-6)&(d>1e-6)))}
    if stored_soc is not None:checks['saved_soc_error_kwh']=float(np.max(np.abs(e-stored_soc)))
    if stored_h is not None:checks['saved_emergency_error_kwh']=float(np.max(np.abs(h-stored_h)))
    checks['emergency_charge_count']=int(np.sum((h>1e-6)&(c>1e-6)))
    if any(v>1e-5 for v in checks.values()):raise AssertionError(checks)
    return h,w,e,checks


def summarize(name,dates,q,c,d,net_kw,price,saved_e=None,saved_h=None):
    h,w,e,checks=validate(q,c,d,net_kw,saved_e,saved_h)
    regular=q@price;emergency=h@(5*price);total=regular+emergency
    events=[];daily=[]
    for day in range(31,len(q)):
        daily.append({'date':str(dates[day]),'planned_cost_yuan':float(regular[day]),
            'emergency_cost_yuan':float(emergency[day]),'total_cost_yuan':float(total[day]),
            'planned_kwh':float(q[day].sum()),'emergency_kwh':float(h[day].sum()),
            'charge_kwh':float(c[day].sum()),'discharge_kwh':float(d[day].sum()),
            'surplus_kwh':float(w[day].sum()),'soc_start_kwh':float(e[day,0]),'soc_end_kwh':float(e[day,-1])})
        start=None
        for t in range(145):
            active=t<144 and h[day,t]>1e-6
            if active and start is None:start=t
            if not active and start is not None:
                events.append({'date':str(dates[day]),'interval':time_label(start)+'-'+time_label(t),
                               'kwh':float(h[day,start:t].sum()),'cost_yuan':float(h[day,start:t]@(5*price[start:t]))})
                start=None
    report={'strategy':name,'evaluation_from':str(dates[31]),'evaluation_to':str(dates[-1]),
        'days':len(q)-31,'planned_cost_yuan':float(regular[31:].sum()),
        'emergency_cost_yuan':float(emergency[31:].sum()),'total_cost_yuan':float(total[31:].sum()),
        'emergency_kwh':float(h[31:].sum()),'emergency_intervals':int((h[31:]>1e-6).sum()),
        'emergency_events':len(events),'surplus_kwh':float(w[31:].sum()),
        'initial_feb_soc_kwh':float(e[31,0]),'terminal_soc_kwh':float(e[-1,-1]),
        'emergency_and_charge_intervals':int(((h[31:]>1e-6)&(c[31:]>1e-6)).sum()),
        'checks':checks,'daily':daily,
        'source_hashes':load_data().sources}
    dump_json(OUT/f'{name}_report.json',report)
    dump_json(OUT/f'{name}_events.json',events)
    np.savez_compressed(OUT/f'{name}_verified.npz',dates=dates,q=q,c=c,d=d,h=h,w=w,soc=e,
                        planned_cost=regular,emergency_cost=emergency)
    return report



def main():
    data=load_data();a=np.load(OUT/'trajectory.npz')
    report=summarize('final',a['dates'],a['q'],a['c'],a['d'],data.net_kw,data.price,a['soc'],a['h'])
    print({k:report[k] for k in ['total_cost_yuan','emergency_cost_yuan','initial_feb_soc_kwh','terminal_soc_kwh','checks']})

if __name__=='__main__':main()

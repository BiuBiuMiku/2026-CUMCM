"""Independent checks and workbook rows for Question 4-3."""
import sys,json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from common import ROOT,ETA,EMIN,EMAX,U,E0,DT,label,load_all,sha256


def validate(name):
    out=HERE/"results";a=np.load(out/f"{name}.npz");data,price2=load_all();price=price2.reshape(-1);net=data.net_kw.reshape(-1)*DT
    q,c,d,h,w,e=[a[k] for k in ["q","c","d","h","w","e"]];q0=a["q0"];qf=a["qfinal"];delta=a["delta"]
    scenario_ids=a["scenario_ids"];future_scenarios=0;wrong_issue_time=0
    for day in range(365):
        for r in range(4):
            k=day*4+r;used=scenario_ids[day,r][scenario_ids[day,r]>=0]
            future_scenarios+=int(np.sum(used*36+144>=k*36))
            wrong_issue_time+=int(np.sum(used%4!=r))
    rebuilt=E0+np.r_[0,np.cumsum(ETA*c-d/ETA)]
    checks={"soc":float(np.abs(rebuilt-e).max()),"balance":float(np.abs(q+h+d-net-c-w).max()),
            "bounds":float(max(0,EMIN-e.min(),e.max()-EMAX)),"power":float(max(0,(c+d).max()-U)),
            "plan":float(np.abs(q0+delta.sum(1)-qf).max()),"mapping":float(np.abs(q.reshape(365,144)-qf).max()),
            "emergency_charge":int(((h>1e-7)&(c>1e-7)).sum()),"simultaneous":int(((c>1e-7)&(d>1e-7)).sum()),"lp":float(a["lp_residual"])}
    checks["future_scenarios"]=future_scenarios;checks["wrong_issue_time"]=wrong_issue_time
    if any(v>1e-5 for v in checks.values()):raise AssertionError(checks)
    p2=price2;original=q0*p2;adjust=((1.5*np.maximum(delta,0)-.5*np.maximum(-delta,0))*p2[:,None,:]).sum(1);trade=original+adjust
    emergency=5*h.reshape(365,144)*p2;events=[];battery=[]
    for day in range(31,365):
        serial=45658+day
        for b in range(6):
            sl=slice(day*144+b*24,day*144+(b+1)*24);battery.append([serial if b==0 else None,f"{b*4}:00-{(b+1)*4}:00",float(c[sl].sum()),float(d[sl].sum()),0 if b==0 else ("24:00" if b==1 else None),float(e[day*144]) if b==0 else (float(e[(day+1)*144]) if b==1 else None)])
        start=None
        for t in range(145):
            active=t<144 and h[day*144+t]>1e-7
            if active and start is None:start=t
            if not active and start is not None:
                events.append([serial if not any(r[0]==serial for r in events) else None,label(start)+"-"+label(t),float(h[day*144+start:day*144+t].sum())]);start=None
    report={"variant":name,"days":334,"planned_cost":float(original[31:].sum()),"adjustment_net_cost":float(adjust[31:].sum()),
            "emergency_cost":float(emergency[31:].sum()),"total_cost":float(trade[31:].sum()+emergency[31:].sum()),
            "emergency_kwh":float(h[31*144:].sum()),"initial_feb_soc":float(e[31*144]),"terminal_soc":float(e[-1]),
            "accepted_updates":{str((r+1)*6):int((a["gains"][31:,r]>0).sum()) for r in range(3)},"checks":checks}
    if name=="main":
        tables={"plan":[[45658+day,*q0[day].tolist(),float(q0[day].sum()),float(original[day].sum())] for day in range(31,365)],
                "adjusted":[[45658+day,*qf[day].tolist(),float(qf[day].sum()),float(trade[day].sum())] for day in range(31,365)],"battery":battery,"emergency":events}
        (out/"tables.json").write_text(json.dumps(tables,ensure_ascii=False),encoding="utf-8")
    return report


def main():
    result={name:validate(name) for name in ["main","only0"]};(HERE/"results"/"report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":main()

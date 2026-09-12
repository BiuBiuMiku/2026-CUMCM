"""Independent checks, cost ledger and workbook rows for Question 4-2."""
import sys,json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from common import ROOT,ETA,EMIN,EMAX,U,E0,DT,label,load_all,sha256


def main():
    out=HERE/"results";a=np.load(out/"trajectory.npz");data,price=load_all();net=data.net_kw*DT
    q,c,d,h,w,e=[a[k] for k in ["q","c","d","h","w","e"]]
    scenario_ids=a["scenario_ids"]
    future_scenarios=0
    for day in range(365):
        used=scenario_ids[day][scenario_ids[day]>=0]
        future_scenarios+=int(np.sum(used>=day))
    rebuilt=E0+np.r_[0,np.cumsum((ETA*c-d/ETA).reshape(-1))]
    stored=np.r_[e[:,:-1].reshape(-1),e[-1,-1]]
    checks={"soc":float(np.abs(rebuilt-stored).max()),
            "balance":float(np.abs(q+h+d-net-c-w).max()),"bounds":float(max(0,EMIN-e.min(),e.max()-EMAX)),
            "power":float(max(0,(c+d).max()-U)),"emergency_charge":int(((h>1e-7)&(c>1e-7)).sum()),
            "simultaneous":int(((c>1e-7)&(d>1e-7)).sum()),"future_scenarios":future_scenarios,
            "lp":float(a["lp_residual"])}
    if any(v>1e-5 for v in checks.values()):raise AssertionError(checks)
    normal=q*price;emergency=5*h*price;events=[];battery=[]
    for day in range(31,365):
        serial=45658+day
        for b in range(6):
            sl=slice(b*24,(b+1)*24);battery.append([serial if b==0 else None,f"{b*4}:00-{(b+1)*4}:00",float(c[day,sl].sum()),float(d[day,sl].sum()),0 if b==0 else ("24:00" if b==1 else None),float(e[day,0]) if b==0 else (float(e[day,-1]) if b==1 else None)])
        start=None
        for t in range(145):
            active=t<144 and h[day,t]>1e-7
            if active and start is None:start=t
            if not active and start is not None:
                events.append([serial if not any(r[0]==serial for r in events) else None,label(start)+"-"+label(t),float(h[day,start:t].sum())]);start=None
    rows=[[45658+day,*q[day].tolist(),float(q[day].sum()),float(normal[day].sum())] for day in range(31,365)]
    tables={"plan":rows,"battery":battery,"emergency":events};(out/"tables.json").write_text(json.dumps(tables,ensure_ascii=False),encoding="utf-8")
    report={"days":334,"normal_cost_yuan":float(normal[31:].sum()),"emergency_cost_yuan":float(emergency[31:].sum()),
            "total_cost_yuan":float((normal+emergency)[31:].sum()),"emergency_kwh":float(h[31:].sum()),
            "initial_feb_soc":float(e[31,0]),"terminal_soc":float(e[-1,-1]),"checks":checks,
            "source_hashes":{"attachment4":sha256(ROOT/"C题"/"附件"/"附件4.xlsx")}}
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":main()

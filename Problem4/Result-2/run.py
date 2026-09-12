"""Question 4-2: 00:00 joint price/net-load scenarios and one daily LP."""
import sys,time,json
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from common import ROOT,E0,DT,load_all
from optimizer import solve,feedback


def scenarios(day,nf,pf,actual_net,actual_price,count=8):
    candidates=np.arange(max(21,day-90),day)
    candidates=candidates[(nf["cutoff_ids"][candidates]>=0)&(nf["cutoff_ids"][candidates]<=candidates)]
    candidates=np.array([j for j in candidates if np.isfinite(pf["errors"][j*4]).all()],int)
    if not len(candidates):return nf["forecast"][day:day+1],pf["forecast"][day*4:day*4+1],np.full(count,-1)
    rng=np.random.default_rng(5200+day)
    ids=candidates[np.minimum(len(candidates)-1,((np.arange(count)+rng.random(count))/count*len(candidates)).astype(int))]
    net=nf["forecast"][day]+actual_net[ids]-nf["forecast"][ids]
    price=np.maximum(.001,pf["forecast"][day*4]+actual_price[ids]-pf["forecast"][ids*4])
    return net,price,ids


def main():
    out=HERE/"results";out.mkdir(exist_ok=True)
    data,actual_price=load_all();actual_net=data.net_kw
    nf=np.load(ROOT/"Problem2"/"results"/"forecasts.npz");pf=np.load(HERE.parent/"price-results"/"price_forecasts.npz")
    q,c,d,h,w=[np.zeros((365,144)) for _ in range(5)];e=np.zeros((365,145));ids=np.full((365,8),-1);state=E0;worst=0
    started=time.perf_counter()
    for day in range(365):
        e[day,0]=state
        if day<31:net_paths=nf["baseline"][day:day+1];price_paths=pf["baseline"][day*4:day*4+1]
        else:net_paths,price_paths,ids[day]=scenarios(day,nf,pf,actual_net,actual_price)
        q[day],res=solve(net_paths,price_paths,state);worst=max(worst,res)
        for t in range(144):
            c[day,t],d[day,t],h[day,t],w[day,t],state=feedback(q[day,t],actual_net[day,t]*DT,state);e[day,t+1]=state
        if day%60==0:print(data.dates[day],round(time.perf_counter()-started,1),flush=True)
    np.savez_compressed(out/"trajectory.npz",dates=data.dates,q=q,c=c,d=d,h=h,w=w,e=e,scenario_ids=ids,lp_residual=worst)

if __name__=="__main__":main()

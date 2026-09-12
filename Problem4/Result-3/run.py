"""Question 4-3: 00/06/12/18 updates with joint price/net-load scenarios."""
import sys,time,argparse
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE.parent))
from common import ROOT,E0,DT,load_all
from optimizer import solve,feedback,score


def scenarios(k,nf,pf,count):
    ids=np.array([i for i in range(max(28,k-360),k) if i%4==k%4 and i*36+144<k*36],int)
    ids=ids[np.isfinite(nf["errors"][ids]).all(1)&np.isfinite(pf["errors"][ids]).all(1)]
    if not len(ids):return nf["net"][k:k+1],pf["forecast"][k:k+1],np.full(count,-1)
    rng=np.random.default_rng(7300+k);chosen=ids[np.minimum(len(ids)-1,((np.arange(count)+rng.random(count))/count*len(ids)).astype(int))]
    net=nf["net"][k]+nf["errors"][chosen]
    price=np.maximum(.001,pf["forecast"][k]+pf["errors"][chosen])
    return net,price,chosen


def run(name,updates,count=8):
    out=HERE/"results";out.mkdir(exist_ok=True);data,actual_price=load_all();truth=data.net_kw.reshape(-1)
    nf=np.load(ROOT/"Problem3-New"/"results"/"forecasts.npz");pf=np.load(HERE.parent/"price-results"/"price_forecasts.npz")
    n=365*144;executed=np.zeros(n);c=np.zeros(n);d=np.zeros(n);h=np.zeros(n);w=np.zeros(n);e=np.zeros(n+1);e[0]=E0
    q0=np.zeros((365,144));final=np.zeros_like(q0);delta=np.zeros((365,3,144));gains=np.zeros((365,3));ids=np.full((365,4,count),-1);worst=0;started=time.perf_counter()
    for day in range(365):
        for r in range(4):
            k=day*4+r;start=k*36;net_paths,price_paths,ids[day,r]=scenarios(k,nf,pf,count)
            if r==0:q,res=solve(net_paths,price_paths,e[start]);q0[day]=q;final[day]=q
            elif r*6 in updates:
                offset=r*36;old=final[day,offset:].copy();q,res=solve(net_paths,price_paths,e[start],old)
                unchanged=q.copy();unchanged[:len(old)]=old;gain=score(unchanged,net_paths,price_paths,e[start],old)-score(q,net_paths,price_paths,e[start],old)
                if gain>1e-6:final[day,offset:]=q[:len(old)];delta[day,r-1,offset:]=q[:len(old)]-old;gains[day,r-1]=gain
            else:res=0
            worst=max(worst,res)
            for t in range(start,start+36):
                local=t-day*144;executed[t]=final[day,local]
                c[t],d[t],h[t],w[t],e[t+1]=feedback(executed[t],truth[t]*DT,e[t])
        if day%60==0:print(name,data.dates[day],round(time.perf_counter()-started,1),flush=True)
    np.savez_compressed(out/f"{name}.npz",q0=q0,qfinal=final,q=executed,c=c,d=d,h=h,w=w,e=e,delta=delta,gains=gains,scenario_ids=ids,lp_residual=worst)


def main():
    p=argparse.ArgumentParser();p.add_argument("--variant",default="all",choices=["all","main","only0"]);a=p.parse_args()
    variants={"main":(6,12,18),"only0":()}
    for name,updates in variants.items():
        if a.variant in ("all",name):run(name,updates)
if __name__=="__main__":main()

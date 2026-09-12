"""Four issue-time LPs, OOS residual paths, causal feedback and explicit ledger."""
import argparse
import importlib.util
import json
import sys
import time
import warnings
import numpy as np
from forecast import ROOT, OUT, data_arrays

spec=importlib.util.spec_from_file_location('p2_schedule',ROOT/'Problem2/02_schedule.py')
p2=importlib.util.module_from_spec(spec);spec.loader.exec_module(p2)
linprog,coo_matrix=p2.linprog,p2.coo_matrix
ETA,EMIN,EMAX,U=.9,1200.,10800.,5000/6


def lp(paths,price,state,old=None,fixed_first=None):
    """Scenario LP with history-grouped storage actions; execution is feedback.

    This is a planning approximation, not the exact optimization of the min/max
    feedback policy. Candidate plans are evaluated under that same causal policy.
    """
    net=paths/6;S,T=net.shape
    nodes=p2.history_groups(net-net.mean(0),branch_steps=36,max_depth=2)
    action=np.empty((S,T),int);G=0
    for t in range(T):
        for label in np.unique(nodes[:,t]):action[nodes[:,t]==label,t]=G;G+=1
    H=T+2*G;E=H+S*T;B=E+S*(T+1);M=0 if old is None else len(old);nv=B+2*M
    objective=np.zeros(nv);objective[:T]=price
    bounds=[(0,None)]*nv
    for s in range(S):
        for t in range(T+1):bounds[E+s*(T+1)+t]=(EMIN,EMAX)
        # E is internal battery energy. Replacing 1 kWh of terminal E at the
        # next valley requires 1/ETA kWh of grid-side charging energy.
        objective[E+s*(T+1)+T]=-float(price.min())/(ETA*S)
    objective[H:E]=np.tile(5*price/S,S)
    if fixed_first is not None:bounds[0]=(fixed_first,fixed_first);objective[0]=0
    if old is not None:
        objective[:M]=0
        objective[B:B+M]=1.5*price[:M]
        objective[B+M:]=-.5*price[:M]
    er=[];ec=[];ev=[];eb=[];ur=[];uc=[];uv=[];ub=[]
    def eq(cols,vals,rhs=0.):er.extend([len(eb)]*len(cols));ec.extend(cols);ev.extend(vals);eb.append(rhs)
    def le(cols,vals,rhs):ur.extend([len(ub)]*len(cols));uc.extend(cols);uv.extend(vals);ub.append(rhs)
    for t in range(M):eq([t,B+t,B+M+t],[1,-1,1],old[t])
    for s in range(S):
        eq([E+s*(T+1)],[1],state)
        for t in range(T):
            c=T+action[s,t];d=T+G+action[s,t];h=H+s*T+t;e=E+s*(T+1)+t
            le([t,c,d,h],[-1,1,-1,-1],-net[s,t])
            eq([e+1,e,c,d],[1,-1,-ETA,1/ETA])
    for t in range(T):
        for g in np.unique(action[:,t]):le([T+g,T+G+g],[1,1],U)
    ae=coo_matrix((ev,(er,ec)),shape=(len(eb),nv)).tocsr()
    au=coo_matrix((uv,(ur,uc)),shape=(len(ub),nv)).tocsr()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',p2.OptimizeWarning)
        res=linprog(objective,A_eq=ae,b_eq=eb,A_ub=au,b_ub=ub,bounds=bounds,method='highs',
            options={'threads':1,'primal_feasibility_tolerance':1e-8,'dual_feasibility_tolerance':1e-8})
    if not res.success:raise RuntimeError(res.message)
    residual=max(np.abs(ae@res.x-eb).max(),max(0,(au@res.x-ub).max()))
    assert residual<1e-5
    return np.maximum(0,res.x[:T]),float(residual)


def score(q,paths,price,state,old=None,fixed_first=False):
    S,T=paths.shape;energy=np.full(S,state);cost=np.zeros(S)
    for t in range(T):
        gap=q[t]-paths[:,t]/6
        c=np.minimum(np.maximum(gap,0),np.minimum(U,np.maximum(0,(EMAX-energy)/ETA)))
        d=np.minimum(np.maximum(-gap,0),np.minimum(U,np.maximum(0,(energy-EMIN)*ETA)))
        h=np.maximum(-gap-d,0);energy+=ETA*c-d/ETA;cost+=5*price[t]*h
    if old is None:purchase=float(q@price)-(q[0]*price[0] if fixed_first else 0.)
    else:
        delta=q[:len(old)]-old
        purchase=float(price[:len(old)]@(1.5*np.maximum(delta,0)-.5*np.maximum(-delta,0))+q[len(old):]@price[len(old):])
    return float(purchase+cost.mean()-price.min()/ETA*energy.mean())


def scenarios(f,k,count):
    # Same issue hour, completed 24h trajectories, strictly before current issue.
    ids=np.arange(max(28,k-4*90),k-4,4,dtype=int)
    ids=ids[(ids%4)==k%4]
    # range start must share the current issuance hour even near cold start.
    ids=np.array([i for i in range(max(28,k-360),k) if i%4==k%4 and i*36+144<k*36],int)
    ids=ids[np.isfinite(f['errors'][ids]).all(1)]
    if not len(ids):return f['net'][k:k+1],np.full(count,-1)
    rng=np.random.default_rng(8700+k)
    chosen=ids[np.minimum(len(ids)-1,((np.arange(count)+rng.random(count))/count*len(ids)).astype(int))]
    assert np.all(chosen*36+144<k*36)
    assert np.all(f['pv_cut'][chosen]<=chosen*36)
    assert np.all(f['q2_cut'][chosen//4] <= (chosen//4)*144)
    return f['net'][k]+f['errors'][chosen],chosen


def run(name,updates,f,count,days):
    data,load,pv,price=data_arrays();truth=load-pv
    n=days*144
    executed=np.zeros(n);c=np.zeros(n);d=np.zeros(n);h=np.zeros(n);w=np.zeros(n);e=np.zeros(n+1);e[0]=6000
    q0=np.zeros((days,144));final=np.zeros_like(q0);versions=np.zeros((days,4,144))
    delta=np.zeros((days,3,144));chosen=np.full((days,4,count),-1);gains=np.zeros((days,3))
    worst=0.;started=time.perf_counter()
    for day in range(days):
        for r in range(4):
            k=day*4+r;start=k*36;periods=np.arange(start,start+144)
            pp=price[periods%144];paths,ids=scenarios(f,k,count);chosen[day,r]=ids
            if r==0:
                q,res=lp(paths,pp,e[start]);worst=max(worst,res)
                q0[day]=q;final[day]=q0[day]
            elif r*6 in updates:
                offset=r*36;old=final[day,offset:].copy()
                q,res=lp(paths,pp,e[start],old=old);worst=max(worst,res)
                unchanged=q.copy();unchanged[:len(old)]=old
                gain=score(unchanged,paths,pp,e[start],old)-score(q,paths,pp,e[start],old)
                # Compare current plan and LP candidate under the exact same
                # non-anticipating feedback, scenario paths and shadow tail.
                if gain>1e-6:
                    final[day,offset:]=q[:len(old)];gains[day,r-1]=gain
                    delta[day,r-1,offset:]=q[:len(old)]-old
            versions[day,r]=final[day]
            for t in range(start,start+36):
                offset=t-day*144
                executed[t]=final[day,offset]
                c[t],d[t],h[t],w[t],e[t+1]=p2.feedback(executed[t],truth[t]/6,e[t])
        if day%30==0 or day==days-1:
            print(name,str(data.dates[day]),'seconds',round(time.perf_counter()-started,1),flush=True)
    np.savez_compressed(OUT/f'{name}.npz',q0=q0,qfinal=final,versions=versions,delta=delta,
        q=executed,c=c,d=d,h=h,w=w,e=e,scenario_ids=chosen,gains=gains,lp_residual=worst)
    print(name,'finished',round(time.perf_counter()-started,1),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--days',type=int,default=365);p.add_argument('--scenarios',type=int,default=8)
    p.add_argument('--variant',default='all',choices=['all','main','only0','no6','no12','no18']);a=p.parse_args()
    f=np.load(OUT/'forecasts.npz')
    variants={'main':(6,12,18),'only0':(),'no6':(12,18),'no12':(6,18),'no18':(6,12)}
    for name,updates in variants.items():
        if a.variant in ('all',name):run(name,updates,f,a.scenarios,a.days)


if __name__=='__main__':main()

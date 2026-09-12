"""Scenario LP and real-time battery feedback shared by both Problem 4 branches."""
import sys, warnings
import numpy as np
from common import ROOT, DT, ETA, EMIN, EMAX, U
sys.path.insert(0,str(ROOT/"Problem2"))
try:
    from scipy.optimize import linprog, OptimizeWarning
    from scipy.sparse import coo_matrix
except ModuleNotFoundError:
    sys.path.insert(0,str(ROOT/"tmp"/"problem2_dependencies"))
    from scipy.optimize import linprog, OptimizeWarning
    from scipy.sparse import coo_matrix


def joint_groups(net_error,price_error,branch_steps=36,max_depth=2):
    """Split scenarios only from errors revealed before the current period."""
    S,T=net_error.shape;nodes=np.zeros((S,T),int);labels=np.zeros(S,int);next_label=1;done=0
    net_scale=max(float(np.std(net_error)),1e-6);price_scale=max(float(np.std(price_error)),1e-6)
    for t in range(T):
        while done<max_depth and t>=(done+1)*branch_steps:
            score=net_error[:,:t].sum(1)/net_scale+price_error[:,:t].sum(1)/price_scale
            new=labels.copy()
            for label in np.unique(labels):
                members=np.flatnonzero(labels==label);threshold=np.median(score[members])
                high=members[score[members]>threshold+1e-10]
                if 0<len(high)<len(members):new[high]=next_label;next_label+=1
            labels=new;done+=1
        nodes[:,t]=labels
    return nodes


def solve(net_paths_kw,price_paths,state,old=None):
    net=net_paths_kw*DT; S,T=net.shape
    if price_paths.shape!=(S,T): raise ValueError("net and price scenario shapes differ")
    nodes=joint_groups(net-net.mean(0),price_paths-price_paths.mean(0))
    action=np.empty((S,T),int); G=0
    for t in range(T):
        for g in np.unique(nodes[:,t]): action[nodes[:,t]==g,t]=G;G+=1
    H=T+2*G; E=H+S*T; M=0 if old is None else len(old); B=E+S*(T+1); nv=B+2*M
    obj=np.zeros(nv); avg=price_paths.mean(0); obj[:T]=avg
    obj[H:E]=(5*price_paths/S).reshape(-1)
    bounds=[(0,None)]*nv
    for s in range(S):
        for t in range(T+1): bounds[E+s*(T+1)+t]=(EMIN,EMAX)
        obj[E+s*(T+1)+T]=-float(price_paths[s].min())/(ETA*S)
    if old is not None:
        obj[:M]=0; obj[B:B+M]=1.5*avg[:M]; obj[B+M:]=-.5*avg[:M]
    er=[];ec=[];ev=[];eb=[];ur=[];uc=[];uv=[];ub=[]
    def eq(cols,vals,rhs=0): er.extend([len(eb)]*len(cols));ec.extend(cols);ev.extend(vals);eb.append(rhs)
    def le(cols,vals,rhs): ur.extend([len(ub)]*len(cols));uc.extend(cols);uv.extend(vals);ub.append(rhs)
    for t in range(M): eq([t,B+t,B+M+t],[1,-1,1],old[t])
    for s in range(S):
        eq([E+s*(T+1)],[1],state)
        for t in range(T):
            c=T+action[s,t];d=T+G+action[s,t];h=H+s*T+t;e=E+s*(T+1)+t
            le([t,c,d,h],[-1,1,-1,-1],-net[s,t]);eq([e+1,e,c,d],[1,-1,-ETA,1/ETA])
    for t in range(T):
        for g in np.unique(action[:,t]): le([T+g,T+G+g],[1,1],U)
    ae=coo_matrix((ev,(er,ec)),shape=(len(eb),nv)).tocsr(); au=coo_matrix((uv,(ur,uc)),shape=(len(ub),nv)).tocsr()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",OptimizeWarning)
        res=linprog(obj,A_eq=ae,b_eq=eb,A_ub=au,b_ub=ub,bounds=bounds,method="highs",options={"threads":1})
    if not res.success: raise RuntimeError(res.message)
    residual=max(np.abs(ae@res.x-eb).max(),max(0,(au@res.x-ub).max()))
    if residual>1e-5:raise AssertionError(residual)
    return np.maximum(0,res.x[:T]),float(residual)


def feedback(q,net,state):
    gap=float(q-net)
    if gap>=0:
        c=min(gap,U,max(0,(EMAX-state)/ETA));d=h=0.;w=gap-c
    else:
        c=w=0.;d=min(-gap,U,max(0,(state-EMIN)*ETA));h=-gap-d
    return c,d,h,w,state+ETA*c-d/ETA


def score(q,net_paths,price_paths,state,old=None):
    S,T=net_paths.shape;energy=np.full(S,state);cost=np.zeros(S)
    for t in range(T):
        gap=q[t]-net_paths[:,t]*DT
        c=np.minimum(np.maximum(gap,0),np.minimum(U,np.maximum(0,(EMAX-energy)/ETA)))
        d=np.minimum(np.maximum(-gap,0),np.minimum(U,np.maximum(0,(energy-EMIN)*ETA)))
        h=np.maximum(-gap-d,0);energy+=ETA*c-d/ETA;cost+=5*price_paths[:,t]*h
    if old is None: trade=(price_paths*q).sum(1)
    else:
        delta=q[:len(old)]-old
        trade=(price_paths[:,:len(old)]*(1.5*np.maximum(delta,0)-.5*np.maximum(-delta,0))).sum(1)
        trade+=(price_paths[:,len(old):]*q[len(old):]).sum(1)
    return float(np.mean(trade+cost-np.min(price_paths,axis=1)/ETA*energy))

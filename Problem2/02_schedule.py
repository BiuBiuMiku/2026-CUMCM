"""One daily stochastic LP followed by fixed load-first feedback."""
import sys
import warnings
import numpy as np
from common import *

try:
    from scipy.optimize import linprog, OptimizeWarning
    from scipy.sparse import coo_matrix
except ModuleNotFoundError:
    dependency = ROOT / 'tmp' / 'problem2_dependencies'
    if dependency.is_dir():
        sys.path.insert(0, str(dependency))
        from scipy.optimize import linprog, OptimizeWarning
        from scipy.sparse import coo_matrix
    else:
        raise


def history_groups(paths_kwh, branch_steps=36, max_depth=2):
    """Group scenarios only by error history that has already elapsed."""
    scenarios, periods = paths_kwh.shape
    nodes = np.zeros((scenarios, periods), dtype=int)
    labels = np.zeros(scenarios, dtype=int)
    next_label, completed = 1, 0
    for t in range(periods):
        while completed < max_depth and t >= (completed + 1) * branch_steps:
            score = paths_kwh[:, :t].sum(axis=1)
            new = labels.copy()
            for label in np.unique(labels):
                members = np.flatnonzero(labels == label)
                threshold = np.median(score[members])
                high = members[score[members] > threshold + 1e-10]
                if 0 < len(high) < len(members):
                    new[high] = next_label
                    next_label += 1
            labels, completed = new, completed + 1
        nodes[:, t] = labels
    return nodes


def solve(paths_kw, price, initial_soc):
    """Solve the 144-period scenario LP; q is common to every scenario."""
    net = paths_kw * DT
    scenarios, periods = net.shape
    nodes = history_groups(net)
    action = np.empty((scenarios, periods), dtype=int)
    groups = 0
    for t in range(periods):
        for label in np.unique(nodes[:, t]):
            action[nodes[:, t] == label, t] = groups
            groups += 1
    hbase = periods + 2 * groups
    ebase = hbase + scenarios * periods
    nv = ebase + scenarios * (periods + 1)
    ci = lambda s, t: periods + action[s, t]
    di = lambda s, t: periods + groups + action[s, t]
    hi = lambda s, t: hbase + s * periods + t
    ei = lambda s, t: ebase + s * (periods + 1) + t
    objective = np.zeros(nv)
    objective[:periods] = price
    objective[hbase:ebase] = np.tile(5 * price / scenarios, scenarios)
    bounds = [(0, None)] * nv
    for s in range(scenarios):
        for t in range(periods + 1):
            bounds[ei(s, t)] = (E_MIN, E_MAX)
    er, ec, ev, eb, ur, uc, uv, ub = [], [], [], [], [], [], [], []
    def equality(cols, vals, rhs=0.0):
        er.extend([len(eb)] * len(cols)); ec.extend(cols); ev.extend(vals); eb.append(rhs)
    def upper(cols, vals, rhs):
        ur.extend([len(ub)] * len(cols)); uc.extend(cols); uv.extend(vals); ub.append(rhs)
    for s in range(scenarios):
        equality([ei(s, 0)], [1], initial_soc)
        for t in range(periods):
            cidx, didx, hidx = ci(s, t), di(s, t), hi(s, t)
            upper([t, cidx, didx, hidx], [-1, 1, -1, -1], -net[s, t])
            equality([ei(s, t + 1), ei(s, t), cidx, didx], [1, -1, -ETA, 1 / ETA])
    for t in range(periods):
        for node in np.unique(nodes[:, t]):
            s = int(np.flatnonzero(nodes[:, t] == node)[0])
            upper([ci(s, t), di(s, t)], [1, 1], U)
    ae = coo_matrix((ev, (er, ec)), shape=(len(eb), nv)).tocsr()
    au = coo_matrix((uv, (ur, uc)), shape=(len(ub), nv)).tocsr()
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Unrecognized options detected', category=OptimizeWarning)
        result = linprog(objective, A_eq=ae, b_eq=eb, A_ub=au, b_ub=ub,
                         bounds=bounds, method='highs',
                         options={'threads': 1, 'primal_feasibility_tolerance': 1e-8,
                                  'dual_feasibility_tolerance': 1e-8})
    if not result.success:
        raise RuntimeError(result.message)
    equality_error = float(np.max(np.abs(ae @ result.x - np.asarray(eb))))
    inequality_error = float(max(0, np.max(au @ result.x - np.asarray(ub))))
    residual = max(equality_error, inequality_error)
    if residual > 1e-5:
        raise AssertionError(f'LP residual: {residual}')
    return result.x[:periods].copy(), residual

def sample(past,forecast,cutoffs,day,count=8):
    assert len(past)==day
    ids=np.arange(max(21,day-90),day)
    ids=ids[(cutoffs[ids]>=0)&(cutoffs[ids]<=ids)]
    if len(ids)==0: raise ValueError('No settled OOS daily residuals')
    rng=np.random.default_rng(20260911+day)
    selected=ids[np.floor((np.arange(count)+rng.random())/count*len(ids)).astype(int)]
    return forecast[day]+past[selected]-forecast[selected],selected

def feedback(q,net,state):
    a=float(q-net)
    if a>=0:
        c=min(a,U,max(0,(E_MAX-state)/ETA));d=0.;h=0.;w=a-c
    else:
        c=0.;d=min(-a,U,max(0,(state-E_MIN)*ETA));h=-a-d;w=0.
    return c,d,h,w,state+ETA*c-d/ETA

def main():
    data=load_data();f=np.load(OUT/'forecasts.npz');forecast=f['forecast'];actual=data.net_kw
    q,c,d,h,w=[np.zeros((365,144)) for _ in range(5)];e=np.zeros((365,145))
    ids=np.full((365,8),-1);state=E_INITIAL;worst=0.
    for day in range(365):
        e[day,0]=state
        if day<31:paths=f['baseline'][day:day+1]
        else:paths,ids[day]=sample(actual[:day],forecast,f['cutoff_ids'],day)
        q[day], residual=solve(paths,data.price,state)
        worst=max(worst,residual)
        # Nothing from the realized target day is passed to the planner.
        for t in range(144):
            c[day,t],d[day,t],h[day,t],w[day,t],state=feedback(q[day,t],actual[day,t]*DT,state)
            e[day,t+1]=state
        if day%30==0 or day==364: print(data.dates[day],round(state,3),flush=True)
    np.savez_compressed(OUT/'trajectory.npz',dates=data.dates,q=q,c=c,d=d,h=h,w=w,soc=e,scenario_ids=ids)
    print(f'maximum LP residual: {worst:.3e}')
if __name__=='__main__': main()

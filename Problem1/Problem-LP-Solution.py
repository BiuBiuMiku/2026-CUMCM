"""Reproduce the Problem 1 LP under the documented interval-end convention.

Reads the original workbook without changing it. Writes JSON evidence only;
does not fill result1.xlsx because its interval labels need separate mapping.
Usage: python Problem1/verify_problem1_lp.py
Dependencies: numpy, pandas, openpyxl, scipy.
"""

from pathlib import Path
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DEPS = ROOT / "tmp" / "problem1_dependencies"
if LOCAL_DEPS.is_dir():
    sys.path.insert(0, str(LOCAL_DEPS))

import numpy as np
import pandas as pd
import scipy
from scipy.optimize import linprog


def build(price, load, pv, eta_c=0.9, eta_d=0.9):
    n = len(price)
    size = 5 * n + 1
    q, c, discharge, waste, energy = [i * n for i in range(5)]
    objective = np.zeros(size)
    objective[q:q+n] = price
    eq = np.zeros((2*n+2, size))
    rhs = np.zeros(2*n+2)
    ub = np.zeros((n, size))
    for t in range(n):
        eq[t, [q+t, c+t, discharge+t, waste+t]] = [1, -1, 1, -1]
        rhs[t] = load[t] - pv[t]
        eq[n+t, [c+t, discharge+t, energy+t, energy+t+1]] = [-eta_c, 1/eta_d, -1, 1]
        ub[t, [c+t, discharge+t]] = 1
    eq[2*n, energy] = 1
    eq[2*n+1, energy+n] = 1
    rhs[2*n:] = 6000
    bounds = [(0, None)] * (4*n) + [(1200, 10800)] * (n+1)
    return objective, eq, rhs, ub, np.full(n, 5000/6), bounds


def certificate(result, model):
    f, eq, rhs, ub, limits, bounds = model
    x = result.x
    lo = np.array([b[0] for b in bounds], dtype=float)
    hi = np.array([np.inf if b[1] is None else b[1] for b in bounds])
    finite_hi = np.isfinite(hi)
    y = result.eqlin.marginals
    mu = result.ineqlin.marginals
    lower = result.lower.marginals
    upper = result.upper.marginals
    dual = rhs @ y + limits @ mu + lo @ lower + hi[finite_hi] @ upper[finite_hi]
    stationarity = f - eq.T @ y - ub.T @ mu - lower - upper
    return {
        "primal_objective": float(f @ x),
        "dual_objective": float(dual),
        "absolute_duality_gap": float(abs(f @ x-dual)),
        "equality_max_abs_kwh": float(np.max(np.abs(eq @ x-rhs))),
        "inequality_max_violation_kwh": float(max(0, np.max(ub @ x-limits))),
        "bounds_max_violation_kwh": float(max(0, np.max(lo-x), np.max(x[finite_hi]-hi[finite_hi]))),
        "stationarity_max_abs": float(np.max(np.abs(stationarity))),
        "dual_sign_violation": float(max(0, np.max(mu), -np.min(lower), np.max(upper))),
        "complementarity_max_abs": float(max(np.max(np.abs(mu*(limits-ub@x))), np.max(np.abs(lower*(x-lo))), np.max(np.abs(upper[finite_hi]*(hi[finite_hi]-x[finite_hi]))))),
    }


def label(index):
    minute = index * 10
    return f"{minute//60:02d}:{minute%60:02d}"


def main():
    path = ROOT / "C题" / "附件" / "附件1.xlsx"
    data = pd.read_excel(path, sheet_name=0)
    if data.shape != (144, 4):
        raise ValueError(f"Unexpected input shape: {data.shape}")
    values = data.iloc[:, 1:4].apply(pd.to_numeric, errors="raise").to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError("Missing or nonfinite input")
    price, load_power, pv_power = values.T
    if np.min(price) <= 0 or np.min(load_power) < 0 or np.min(pv_power) < 0:
        raise ValueError("Re-audit disposal and data assumptions before solving")
    load, pv = load_power/6, pv_power/6
    model = build(price, load, pv)
    f, eq, rhs, ub, limits, bounds = model
    started = time.perf_counter()
    solution = linprog(f, A_ub=ub, b_ub=limits, A_eq=eq, b_eq=rhs, bounds=bounds, method="highs-ds", options={"primal_feasibility_tolerance": 1e-8, "dual_feasibility_tolerance": 1e-8})
    elapsed = time.perf_counter()-started
    if not solution.success:
        raise RuntimeError(solution.message)
    n = 144
    q, c, discharge, waste = [solution.x[i*n:(i+1)*n].copy() for i in range(4)]
    energy = solution.x[4*n:]
    # Remove loss-only within-interval cycles while preserving q and all SOC endpoints.
    removed = np.minimum(c, discharge/0.81)
    c -= removed
    discharge -= 0.81*removed
    waste += 0.19*removed
    x_clean = np.concatenate([q, c, discharge, waste, energy])
    balance = q+pv+discharge-load-c-waste
    replay = np.r_[6000, 6000+np.cumsum(0.9*c-discharge/0.9)]
    no_storage_q = np.maximum(load-pv, 0)
    no_storage_w = np.maximum(pv-load, 0)
    baseline = float(price @ no_storage_q)
    other = linprog(f, A_ub=ub, b_ub=limits, A_eq=eq, b_eq=rhs, bounds=bounds, method="highs-ipm")
    if not other.success:
        raise RuntimeError(other.message)
    input_bounds = bounds.copy()
    input_bounds[3*n:4*n] = [(0, float(v)) for v in pv]
    pv_only = linprog(f, A_ub=ub, b_ub=limits, A_eq=eq, b_eq=rhs, bounds=input_bounds, method="highs")
    sensitivity = []
    for power_kw, eta in [(4000,0.9),(5000,0.9),(6000,0.9),(5000,0.85),(5000,0.95)]:
        sf, se, sr, su, sl, sb = build(price,load,pv,eta,eta)
        sl[:] = power_kw/6
        sr_result = linprog(sf,A_eq=se,b_eq=sr,A_ub=su,b_ub=sl,bounds=sb,method="highs")
        if not sr_result.success:
            raise RuntimeError(sr_result.message)
        sensitivity.append({"power_kw":power_kw,"eta_each_direction":eta,"cost_yuan":float(sr_result.fun)})
    # Alternative interpretation: timestamps denote starts, with 24:00 moved to 00:00.
    # This is a sensitivity case, not the primary time convention.
    order = np.r_[143,np.arange(143)]
    af, ae, ar, au, al, ab = build(price[order],load[order],pv[order])
    alt = linprog(af,A_eq=ae,b_eq=ar,A_ub=au,b_ub=al,bounds=ab,method="highs")
    if not alt.success:
        raise RuntimeError(alt.message)
    cert = certificate(solution, model)
    if cert["equality_max_abs_kwh"] > 1e-5 or cert["absolute_duality_gap"] > 1e-5:
        raise AssertionError(cert)
    if np.max(np.abs(eq @ x_clean-rhs)) > 1e-5 or np.max(ub @ x_clean-limits) > 1e-5:
        raise AssertionError("Cycle removal violated feasibility")
    if np.max(np.abs(replay-energy)) > 1e-5 or np.max(np.abs(balance)) > 1e-5:
        raise AssertionError("Independent replay failed")
    if np.max(np.minimum(c, discharge)) > 1e-6:
        raise AssertionError("Unexpected residual cycle")
    hours = []
    for block in range(6):
        a, b = block*24, (block+1)*24
        hours.append({"interval": f"{label(a)}–{label(b)}", "charge_kwh": float(c[a:b].sum()), "discharge_kwh": float(discharge[a:b].sum()), "soc_start_kwh": float(energy[a]), "soc_end_kwh": float(energy[b])})
    evidence = {
        "scope": "Reference LP under interval-end interpretation; not a filled competition template",
        "source": str(path.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "time_convention": "input row 00:10 -> physical interval [00:00,00:10); final row 0:00+1 -> [23:50,24:00)",
        "template_warning": "Original template starts at 00:10-00:20 and ends at 0:00+1-0:10+1; do not copy by row without an explicit correction decision",
        "scipy_version": scipy.__version__,
        "method": "highs-ds",
        "status": int(solution.status), "message": solution.message,
        "solve_seconds": elapsed,
        "size": {"variables":len(f), "equalities":len(rhs), "inequalities":len(limits)},
        "data": {"rows":144, "missing":int(data.isna().sum().sum()), "price_min":float(price.min()), "price_max":float(price.max()), "load_kwh":float(load.sum()), "pv_kwh":float(pv.sum())},
        "certificate":cert,
        "results": {"cost_yuan":float(price@q), "purchase_kwh":float(q.sum()), "charge_kwh":float(c.sum()), "discharge_kwh":float(discharge.sum()), "surplus_kwh":float(waste.sum()), "soc_min_kwh":float(energy.min()), "soc_max_kwh":float(energy.max()), "soc_start_kwh":float(energy[0]), "soc_end_kwh":float(energy[-1]), "storage_loss_kwh":float(0.1*c.sum()+(1/0.9-1)*discharge.sum()), "both_positive_intervals":int(np.count_nonzero((c>1e-6)&(discharge>1e-6))), "time_budget_max_kwh":float(np.max(c+discharge)), "cleaned_energy_kwh":float(removed.sum())},
        "independent_checks": {"balance_max_abs_kwh":float(np.max(np.abs(balance))), "soc_replay_max_abs_kwh":float(np.max(np.abs(replay-energy))), "highs_ipm_cost_yuan":float(other.fun), "method_cost_abs_difference_yuan":float(abs(other.fun-solution.fun)), "pv_only_disposal_success":bool(pv_only.success), "pv_only_disposal_cost_yuan":float(pv_only.fun) if pv_only.success else None},
        "baseline": {"name":"no_storage", "cost_yuan":baseline, "purchase_kwh":float(no_storage_q.sum()), "surplus_kwh":float(no_storage_w.sum()), "saving_yuan":baseline-float(price@q), "saving_percent":100*(baseline-float(price@q))/baseline},
        "sensitivity": sensitivity,
        "alternative_start_label_case": {"assumption":"24:00 sample moved to 00:00, other samples interpreted as interval starts", "cost_yuan":float(alt.fun), "difference_from_primary_yuan":float(alt.fun-solution.fun)},
        "specified_intervals": [{"interval":f"{label(hour*6)}–{label(hour*6+1)}", "purchase_kwh":float(q[hour*6])} for hour in [10,12,14,16,18,20]],
        "four_hour_blocks": hours,
        "schedule": [{"t":t, "start":label(t), "end":label(t+1), "source_label":str(data.iloc[t,0]), "price":float(price[t]), "load_kwh":float(load[t]), "pv_kwh":float(pv[t]), "purchase_kwh":float(q[t]), "charge_kwh":float(c[t]), "discharge_kwh":float(discharge[t]), "surplus_kwh":float(waste[t]), "soc_start_kwh":float(energy[t]), "soc_end_kwh":float(energy[t+1])} for t in range(n)],
    }
    output = Path(__file__).resolve().parent / "problem1_lp_evidence.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k:v for k,v in evidence.items() if k != "schedule"}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

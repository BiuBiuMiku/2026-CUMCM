"""Causal Q3 forecasts without retraining the Q2 net-load MLP.

Only pretrained, date-valid Q2 model weights are reused.  No Q2 purchase,
storage, emergency-purchase, replay, report, or archived forecast output is read.
Official photovoltaic forecasts are calibrated with already-trained Q3 PV
calibrators, then used as a delta correction to the Q2 net-load forecast.
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import torch
from torch import nn

from check_inputs import ROOT, forecast_records

sys.path.insert(0, str(ROOT / "Problem2"))
from common import FEATURE_NAMES, all_features, load_data


HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
Q2_MODELS = ROOT / "Problem2" / "results" / "models"
ETA = 0.9


class NetResidualMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(len(FEATURE_NAMES), 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1),
        )

    def forward(self, x):
        return self.layers(x).squeeze(-1)


def data_arrays():
    data = load_data()
    # Attachment 2 uses interval-end labels: 00:10 is [00:00,00:10).
    return data, data.load_kw.reshape(-1), data.pv_kw.reshape(-1), data.price.copy()


def pv_periodic_baseline(data):
    """The historical PV component used by the Q2 periodic net baseline."""
    result = np.zeros((365, 288), dtype=float)
    for day in range(365):
        issue = date.fromisoformat(str(data.dates[day]))
        history = data.pv_kw[:day]
        for ahead in (0, 1):
            target = issue + timedelta(days=ahead)
            if day:
                mean3 = history[-3:].mean(0)
                ids = [i for i in range(max(0, day - 28), day)
                       if (issue - timedelta(days=day - i)).weekday() == target.weekday()]
                same = history[ids].mean(0) if ids else history[-min(7, day):].mean(0)
                value = 0.5 * same + 0.5 * mean3
            else:
                value = np.zeros(144)
            result[day, ahead * 144:(ahead + 1) * 144] = value
    return result


def q2_net_forecasts(data):
    """Recompute forecasts from raw history and frozen Q2 weights only."""
    xx, base = all_features(data)
    forecast = base.copy()
    cutoffs = np.full(365, -1, dtype=int)
    files = sorted(Q2_MODELS.glob("mlp_2025-*.pt"))
    if len(files) != 12:
        raise FileNotFoundError("Expected 12 pretrained Q2 monthly models")
    starts = []
    payloads = []
    for path in files:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        cutoff = (date.fromisoformat(payload["cutoff_date"]) - date(2025, 1, 1)).days
        if payload["features"] != FEATURE_NAMES:
            raise AssertionError(f"Feature mismatch: {path.name}")
        starts.append(cutoff); payloads.append((path, payload))
    for i, (path, payload) in enumerate(payloads):
        start = starts[i]; stop = starts[i + 1] if i + 1 < len(starts) else 365
        model = NetResidualMLP()
        model.load_state_dict(payload["state_dict"]); model.eval()
        mu = np.asarray(payload["x_mean"]); scale = np.asarray(payload["x_scale"])
        inp = torch.as_tensor((xx[start:stop].reshape(-1, len(FEATURE_NAMES)) - mu) / scale,
                              dtype=torch.float32)
        with torch.no_grad():
            correction = model(inp).numpy().reshape(stop - start, 288) * payload["target_scale"]
        forecast[start:stop] = base[start:stop] + payload["alpha"] * correction
        cutoffs[start:stop] = start * 144
    return forecast, base, cutoffs


def time_weight(days):
    return np.clip((np.asarray(days) - 31.0) / 90.0, 0.0, 1.0)


def pv_features(raw):
    issued = np.repeat(np.arange(1460) * 36, 24)
    leads = np.tile(np.arange(1, 25), 1460)
    targets = issued + 6 * leads
    hours = (targets / 6) % 24
    season = targets / (144 * 365.25) * 2 * np.pi
    repeated = np.repeat(raw, 24, axis=0)
    x = np.column_stack([
        raw.reshape(-1), leads / 24,
        np.sin(2 * np.pi * hours / 24), np.cos(2 * np.pi * hours / 24),
        np.sin(season), np.cos(season),
        np.sin(2 * np.pi * (issued % 144) / 144), np.cos(2 * np.pi * (issued % 144) / 144),
        repeated.mean(1), repeated.max(1),
    ]).astype(np.float32)
    groups = ((issued % 144) // 36) * 4 + (leads - 1) // 6
    return x, issued, targets, groups


def calibrated_official_pv(actual_pv):
    records = forecast_records()
    raw = np.array([r[3] for r in records], dtype=float).reshape(1460, 24)
    x, issued, targets, groups = pv_features(raw)
    labels = np.full(len(targets), np.nan)
    valid = (targets >= 1) & (targets <= len(actual_pv))
    labels[valid] = actual_pv[targets[valid] - 1] - raw.reshape(-1)[valid]

    def past_bias(mask):
        sums = np.bincount(groups[mask], weights=labels[mask], minlength=16)
        counts = np.bincount(groups[mask], minlength=16)
        return sums / (counts + 20.0)

    calibrated = raw.copy()
    model_cut = np.full(1460, -1, dtype=int)
    # January: only labels strictly before each issue day's midnight are used.
    for day in range(31):
        mask = (targets < day * 144) & np.isfinite(labels)
        bias = past_bias(mask)
        sl = slice(day * 96, (day + 1) * 96)
        values = raw[day * 4:(day + 1) * 4]
        calibrated[day * 4:(day + 1) * 4] = np.where(
            values > 0, np.maximum(0, values + bias[groups[sl]].reshape(4, 24)), 0)
        model_cut[day * 4:(day + 1) * 4] = day * 144

    month_starts = [(date(2025, m, 1) - date(2025, 1, 1)).days for m in range(2, 13)]
    for i, start in enumerate(month_starts):
        stop = month_starts[i + 1] if i + 1 < len(month_starts) else 365
        path = OUT / "models" / f"pv_{date(2025,1,1)+timedelta(days=start)}.pt"
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if payload["cutoff"] != start * 144:
            raise AssertionError(f"PV cutoff mismatch: {path.name}")
        bias = np.asarray(payload["bias"])
        sl = slice(start * 96, stop * 96)
        correction = bias[groups[sl]].astype(float)
        if "state" in payload and payload["gamma"] > 0:
            model = nn.Sequential(
                nn.Linear(x.shape[1], 32), nn.ReLU(),
                nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1),
            )
            model.load_state_dict(payload["state"]); model.eval()
            mu = np.asarray(payload["mean"]); scale = np.asarray(payload["scale"])
            with torch.no_grad():
                learned = model(torch.as_tensor((x[sl] - mu) / scale, dtype=torch.float32)).squeeze(-1).numpy()
            learned *= payload["target_scale"]
            weight = payload["gamma"] * time_weight(issued[sl] // 144)
            correction = (1 - weight) * correction + weight * learned
        values = raw[start * 4:stop * 4]
        calibrated[start * 4:stop * 4] = np.where(
            values > 0, np.maximum(0, values + correction.reshape(-1, 24)), 0)
        model_cut[start * 4:stop * 4] = start * 144
        assert payload["validation_max_target"] < payload["cutoff"]
    return raw, calibrated, model_cut


def issue_components(q2_net, pv_base, official, actual_pv):
    """Build the causal Q2 reference and official-minus-historical PV delta."""
    base_net = np.empty((1460, 144), dtype=float)
    official_10m = np.empty_like(base_net)
    baseline_10m = np.empty_like(base_net)
    for k in range(1460):
        day, revision = divmod(k, 4)
        offset = revision * 36
        anchor = 0.0 if k == 0 else actual_pv[k * 36 - 1]
        nodes = np.interp(np.arange(145), np.arange(0, 145, 6), np.r_[anchor, official[k]])
        p_off = nodes[:-1]
        p_base = pv_base[day, offset:offset + 144]
        n2 = q2_net[day, offset:offset + 144]
        base_net[k] = n2
        official_10m[k] = p_off; baseline_10m[k] = p_base
    return base_net, official_10m, baseline_10m


def calibrated_beta(base_net, pv_delta, actual_net):
    """Select beta only from observations completed before each month starts.

    One coefficient is used for each issue hour and six-hour lead block.  The
    candidate grid and 1% improvement gate are fixed in advance.  January uses
    beta=0 because no prior-month archive exists.
    """
    candidates = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
    by_day = np.zeros((365, 4, 4), dtype=float)
    records = []
    starts = [(date(2025, m, 1) - date(2025, 1, 1)).days for m in range(2, 13)]
    for i, cutoff in enumerate(starts):
        stop = starts[i + 1] if i + 1 < len(starts) else 365
        chosen = np.zeros((4, 4), dtype=float)
        for revision in range(4):
            issue_days = np.arange(max(0, cutoff - 28), cutoff)
            issue_ids = issue_days * 4 + revision
            for block in range(4):
                slots = np.arange(block * 36, (block + 1) * 36)
                kk, tt = np.meshgrid(issue_ids, slots, indexing="ij")
                targets = kk * 36 + tt
                mature = targets < cutoff * 144
                kk = kk[mature]; tt = tt[mature]; targets = targets[mature]
                observed = actual_net[targets]
                reference = base_net[kk, tt]
                delta = pv_delta[kk, tt]
                mse = np.array([np.mean((observed - (reference - b * delta)) ** 2)
                                for b in candidates])
                best = int(np.argmin(mse))
                beta = float(candidates[best]) if mse[best] < 0.99 * mse[0] else 0.0
                chosen[revision, block] = beta
                records.append({"month": str(date(2025, 1, 1) + timedelta(days=cutoff))[:7],
                                "issue_hour": revision * 6, "lead_hours": f"{block*6}-{(block+1)*6}",
                                "beta": beta, "samples": int(len(observed)),
                                "mse_beta0": float(mse[0]), "mse_selected": float(mse[best])})
        by_day[cutoff:stop] = chosen
    return by_day, records


def issue_paths(base_net, official_10m, baseline_10m, beta_by_day):
    delta = official_10m - baseline_10m
    result = np.empty_like(base_net)
    for k in range(1460):
        day, revision = divmod(k, 4)
        weights = np.repeat(beta_by_day[day, revision], 36)
        result[k] = base_net[k] - weights * delta[k]
    return result


def main():
    torch.set_num_threads(2); OUT.mkdir(exist_ok=True); (OUT / "models").mkdir(exist_ok=True)
    data, load, pv, price = data_arrays()
    q2_net, q2_base, q2_cut = q2_net_forecasts(data)
    pv_base = pv_periodic_baseline(data)
    raw_pv, calibrated_pv, pv_cut = calibrated_official_pv(pv)
    truth = load - pv
    base_issue_net, official_10m, baseline_10m = issue_components(q2_net, pv_base, calibrated_pv, pv)
    beta_by_day, beta_records = calibrated_beta(
        base_issue_net, official_10m - baseline_10m, truth)
    net = issue_paths(base_issue_net, official_10m, baseline_10m, beta_by_day)
    errors = np.full_like(net, np.nan)
    for k in range(1460):
        length = min(144, len(truth) - k * 36)
        errors[k, :length] = truth[k * 36:k * 36 + length] - net[k, :length]
    np.savez_compressed(
        OUT / "forecasts.npz", net=net, errors=errors, q2_net=q2_net,
        q2_periodic_base=q2_base, pv_periodic_base=pv_base,
        official_raw=raw_pv, official_calibrated=calibrated_pv,
        official_10m=official_10m, baseline_pv_10m=baseline_10m,
        beta_by_day=beta_by_day,
        q2_cut=q2_cut, pv_cut=pv_cut, price=price,
    )
    report = {
        "q2_reused": "monthly model weights, scaler, alpha, feature rule only",
        "q2_outputs_forbidden": ["result2.xlsx", "trajectory.npz", "final_verified.npz",
                                 "final_report.json", "forecasts.npz"],
        "formula": "N3=N2-beta(month,issue-hour,lead-block)*(PV_official_calibrated-PV_historical_baseline)",
        "beta_rule": "grid {0,.25,.5,.75,1}; prior 28 completed days only; require at least 1% MSE improvement; freeze within month",
        "beta_records": beta_records,
        "training_performed": False,
        "mature_error_rule": "a 24-hour error path is usable only after every target has occurred",
        "missing_future_truth_cells": int(np.isnan(errors).sum()),
        "evaluation_net_mae_kw": float(np.abs(errors[31 * 4:][np.isfinite(errors[31 * 4:])]).mean()),
    }
    (OUT / "forecast_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

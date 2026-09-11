"""Monthly residual MLP; save only daily 144-slot forecasts and a January pilot."""
import argparse
import copy
from datetime import date
import time
import numpy as np
import torch
from torch import nn
from common import *


class ResidualMLP(nn.Module):
    """Small network that learns only the error left by the periodic baseline."""
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(len(FEATURE_NAMES), 64), nn.ReLU(),
            nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1)
        )

    def forward(self, x):
        return self.layers(x).squeeze(-1)


def fit_fold(x, y, issue_ids, target_ids, cutoff, config, device):
    """Train one monthly expanding-window model without using target-month truth."""
    validation_start = cutoff - 7
    train_mask = (target_ids < validation_start) & (issue_ids >= 7)
    val_mask = (issue_ids >= validation_start) & (target_ids < cutoff)
    assert target_ids[train_mask].max() < issue_ids[val_mask].min()
    mu = x[train_mask].mean(0)
    scale = np.maximum(x[train_mask].std(0), 1e-3)
    target_scale = max(float(y[train_mask].std()), 100.0)
    tx = torch.as_tensor((x[train_mask] - mu) / scale, device=device)
    ty = torch.as_tensor(y[train_mask] / target_scale, device=device, dtype=torch.float32)
    vx = torch.as_tensor((x[val_mask] - mu) / scale, device=device)
    vy = torch.as_tensor(y[val_mask] / target_scale, device=device, dtype=torch.float32)
    torch.manual_seed(config.seed + cutoff)
    model = ResidualMLP().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-3)
    loss_fn = nn.HuberLoss(delta=1.0)
    best_loss, best_epoch, best_state, stale = float('inf'), 0, None, 0
    for epoch in range(config.epochs):
        model.train()
        permutation = torch.randperm(len(tx), device=device)
        for ids in permutation.split(config.batch_size):
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(tx[ids]), ty[ids])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
        model.eval()
        with torch.no_grad():
            validation_loss = float(loss_fn(model(vx), vy))
        if validation_loss < best_loss - 1e-5:
            best_loss, best_epoch, stale = validation_loss, epoch + 1, 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            stale += 1
        if stale >= 10:
            break
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        correction = model(vx).cpu().numpy() * target_scale
    residual = y[val_mask]
    candidates = [0.0, 0.25, 0.5, 0.75, 1.0]
    scores = [(a, float(np.sqrt(np.mean((residual - a * correction) ** 2)))) for a in candidates]
    alpha = min(scores, key=lambda item: item[1])[0]
    return model, mu, scale, target_scale, alpha, best_epoch, best_state


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--epochs', type=int, default=80)
    p.add_argument('--batch-size', type=int, default=2048)
    p.add_argument('--seed', type=int, default=20260911)
    p.add_argument('--device', default='auto', choices=['auto','cpu','cuda'])
    args = p.parse_args()
    torch.set_num_threads(2)
    device = ('cuda' if torch.cuda.is_available() else 'cpu') if args.device == 'auto' else args.device
    data = load_data()
    xx, base = all_features(data)
    xs, ys, issues, targets = [], [], [], []
    for day in range(7, 365):
        for lead in (0, 1):
            if day+lead >= 365:
                continue
            sl = slice(lead*144, (lead+1)*144)
            xs.append(xx[day, sl]); ys.append(data.net_kw[day+lead]-base[day, sl])
            issues.extend([day]*144); targets.extend([day+lead]*144)
    x = np.concatenate(xs); y = np.concatenate(ys).astype(np.float32)
    issues, targets = np.array(issues), np.array(targets)
    forecast = base.copy(); cutoff_ids = np.full(365, -1)
    alpha = np.zeros(365)
    # January 22 pilot: train targets through Jan14; validate Jan15-Jan21.
    cuts = [21] + [(date(2025,m,1)-date(2025,1,1)).days for m in range(2,13)]
    for cutoff, stop in zip(cuts, cuts[1:]+[365]):
        start = time.perf_counter()
        model, mu, scale, yscale, a, best_epoch, state = fit_fold(
            x, y, issues, targets, cutoff, args, device
        )
        with torch.no_grad():
            inputs = torch.as_tensor((xx[cutoff:stop].reshape(-1,30)-mu)/scale, device=device)
            correction = model(inputs).cpu().numpy().reshape(stop-cutoff,288)*yscale
        forecast[cutoff:stop] = base[cutoff:stop]+a*correction
        cutoff_ids[cutoff:stop] = cutoff; alpha[cutoff:stop] = a
        label = str(data.dates[cutoff])
        (OUT/'models').mkdir(parents=True, exist_ok=True)
        torch.save({'state_dict':state,'x_mean':mu.tolist(),'x_scale':scale.tolist(),
                    'target_scale':yscale,'alpha':a,'cutoff_date':label,'features':FEATURE_NAMES},
                   OUT/'models'/f'mlp_{label}.pt')
        print(f'trained {label}: alpha={a:.2f}, epochs={best_epoch}, seconds={time.perf_counter()-start:.1f}', flush=True)
    np.savez_compressed(OUT/'forecasts.npz', dates=data.dates, forecast=forecast[:,:144], baseline=base[:,:144],
                        cutoff_ids=cutoff_ids, alpha=alpha)
    print(f'evaluation MAE: {np.abs(forecast[31:,:144]-data.net_kw[31:]).mean():.3f} kW')


if __name__ == '__main__':
    main()

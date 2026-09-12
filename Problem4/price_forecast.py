"""Causal monthly residual MLP forecasts for the next 24 hours of price."""
import argparse
import copy
import json
from datetime import date, timedelta
from pathlib import Path
import numpy as np
import torch
from torch import nn
from common import HERE, load_all

OUT = HERE / "price-results"
FEATURES = ["baseline", "previous_day", "previous_week", "recent_mean", "last_price",
            "lead", "hour_sin", "hour_cos", "weekday_sin", "weekday_cos"]


class PriceMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(10, 32), nn.ReLU(),
                                    nn.Linear(32, 16), nn.ReLU(), nn.Linear(16, 1))
    def forward(self, x):
        return self.layers(x).squeeze(-1)


def samples(price):
    flat = price.reshape(-1)
    n = len(flat)
    xx = np.zeros((365 * 4, 144, 10), dtype=np.float32)
    base = np.zeros((365 * 4, 144), dtype=float)
    target = np.zeros((365 * 4, 144), dtype=int)
    issue = np.repeat(np.arange(365 * 4) * 36, 144).reshape(365 * 4, 144)
    for k in range(365 * 4):
        issued = k * 36
        recent = float(flat[max(0, issued - 144):issued].mean()) if issued else 0.5
        last = float(flat[issued - 1]) if issued else recent
        for h in range(144):
            target[k, h] = issued + h
            pd = issued + h - 144
            pw = issued + h - 1008
            vday = float(flat[pd]) if pd >= 0 else recent
            vweek = float(flat[pw]) if pw >= 0 else vday
            b = 0.7 * vday + 0.3 * vweek
            stamp = issued + h
            hour = (stamp % 144) / 6
            weekday = (stamp // 144) % 7
            base[k, h] = b
            xx[k, h] = [b, vday, vweek, recent, last, h / 143,
                        np.sin(2*np.pi*hour/24), np.cos(2*np.pi*hour/24),
                        np.sin(2*np.pi*weekday/7), np.cos(2*np.pi*weekday/7)]
    actual = np.full_like(base, np.nan)
    valid = target < n
    actual[valid] = flat[target[valid]]
    return xx, base, target, issue, actual


def fit(x, y, train, val, seed, epochs):
    mu = x[train].mean(0); scale = np.maximum(x[train].std(0), 1e-4)
    ys = max(float(y[train].std()), 0.05)
    tx = torch.as_tensor((x[train]-mu)/scale, dtype=torch.float32)
    ty = torch.as_tensor(y[train]/ys, dtype=torch.float32)
    vx = torch.as_tensor((x[val]-mu)/scale, dtype=torch.float32)
    vy = torch.as_tensor(y[val]/ys, dtype=torch.float32)
    torch.manual_seed(seed)
    model = PriceMLP(); opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=2e-3)
    best, state, stale, epoch_best = float("inf"), None, 0, 0
    for epoch in range(epochs):
        model.train()
        for ids in torch.randperm(len(tx)).split(4096):
            opt.zero_grad(); loss = nn.functional.huber_loss(model(tx[ids]), ty[ids])
            loss.backward(); opt.step()
        model.eval()
        with torch.no_grad(): score = float(nn.functional.mse_loss(model(vx), vy))
        if score < best - 1e-6:
            best, state, stale, epoch_best = score, copy.deepcopy(model.state_dict()), 0, epoch + 1
        else: stale += 1
        if stale >= 7: break
    model.load_state_dict(state); model.eval()
    with torch.no_grad(): corr = model(vx).numpy() * ys
    candidates = [0, .25, .5, .75, 1]
    alpha = min(candidates, key=lambda a: np.mean((y[val]-a*corr)**2))
    return model, mu, scale, ys, alpha, state, epoch_best


def main():
    p = argparse.ArgumentParser(); p.add_argument("--epochs", type=int, default=35); args = p.parse_args()
    torch.set_num_threads(2); OUT.mkdir(exist_ok=True); (OUT/"models").mkdir(exist_ok=True)
    _, price = load_all(); x3, base3, target3, issue3, actual3 = samples(price)
    x=x3.reshape(-1,10); base=base3.reshape(-1); target=target3.reshape(-1)
    issue=issue3.reshape(-1); actual=actual3.reshape(-1); residual=actual-base
    pred=base3.copy(); cutoffs=np.full(1460,-1,dtype=int); records=[]
    starts=[(date(2025,m,1)-date(2025,1,1)).days for m in range(2,13)]
    for z,cut in enumerate(starts):
        stop=starts[z+1] if z+1<len(starts) else 365
        train=(issue>=7*144)&(target<(cut-7)*144)&np.isfinite(residual)
        val=(issue>=(cut-7)*144)&(target<cut*144)&np.isfinite(residual)
        model,mu,scale,ys,alpha,state,ep=fit(x,residual,train,val,4100+cut,args.epochs)
        sl=slice(cut*4,stop*4); inp=torch.as_tensor((x3[sl].reshape(-1,10)-mu)/scale,dtype=torch.float32)
        with torch.no_grad(): corr=model(inp).numpy().reshape(stop*4-cut*4,144)*ys
        pred[sl]=np.maximum(.001,base3[sl]+alpha*corr); cutoffs[sl]=cut*144
        payload={"state":state,"mean":mu.tolist(),"scale":scale.tolist(),"target_scale":ys,
                 "alpha":alpha,"cutoff":cut*144,"train_max_target":int(target[train].max()),
                 "validation_max_target":int(target[val].max()),"features":FEATURES}
        model_date=date(2025,1,1)+timedelta(days=cut)
        torch.save(payload,OUT/"models"/f"price_{model_date}.pt")
        records.append({"month_start_day":cut,"alpha":alpha,"epochs":ep,
                        "validation_mae":float(np.abs(residual[val]-alpha*(model(torch.as_tensor((x[val]-mu)/scale,dtype=torch.float32)).detach().numpy()*ys)).mean())})
    errors=actual3-pred
    np.savez_compressed(OUT/"price_forecasts.npz",forecast=pred,baseline=base3,errors=errors,cutoff=cutoffs,actual=price)
    report={"rule":"future prices are predicted; actual prices are used only when their interval settles",
            "models":records,"evaluation_mae_yuan_per_kwh":float(np.abs(errors[31*4:][np.isfinite(errors[31*4:])]).mean())}
    (OUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__": main()

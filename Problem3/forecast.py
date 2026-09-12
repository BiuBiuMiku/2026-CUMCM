"""Past-only monthly residual models and archived issue-time forecasts."""
import argparse
import copy
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import numpy as np
import torch
from torch import nn
from check_inputs import ROOT, forecast_records

sys.path.insert(0, str(ROOT/'Problem2'))
from common import load_data, features, read_xlsx

OUT = Path(__file__).resolve().parent/'results'
ORIGIN = datetime(2025,1,1)


def time_weight(days):
    """Predeclared ramp: first 31 history days bias only, next 90 days ramp.

    This is a design choice, not a claimed optimal threshold. gamma is selected
    on past validation and multiplies this time-only envelope.
    """
    return np.clip((np.asarray(days)-31.)/90.,0.,1.)


def fit(x,y,train,val,seed,epochs):
    assert train.any() and val.any()
    mu=x[train].mean(0); scale=np.maximum(x[train].std(0),1e-3)
    ys=max(float(y[train].std()),100.)
    tx=torch.tensor((x[train]-mu)/scale,dtype=torch.float32)
    ty=torch.tensor(y[train]/ys,dtype=torch.float32)
    vx=torch.tensor((x[val]-mu)/scale,dtype=torch.float32)
    vy=torch.tensor(y[val]/ys,dtype=torch.float32)
    torch.manual_seed(seed)
    model=nn.Sequential(nn.Linear(x.shape[1],32),nn.ReLU(),nn.Linear(32,16),nn.ReLU(),nn.Linear(16,1))
    opt=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.003)
    best=float('inf'); state=None; stale=0; best_epoch=0
    for ep in range(epochs):
        for ids in torch.randperm(len(tx)).split(2048):
            opt.zero_grad(); loss=nn.functional.huber_loss(model(tx[ids]).squeeze(-1),ty[ids]);loss.backward();opt.step()
        with torch.no_grad(): score=float(nn.functional.mse_loss(model(vx).squeeze(-1),vy))
        if score<best-1e-5:best=score;state=copy.deepcopy(model.state_dict());stale=0;best_epoch=ep+1
        else:stale+=1
        if stale>=8:break
    model.load_state_dict(state);model.eval()
    def predict(z):
        with torch.no_grad():return model(torch.tensor((z-mu)/scale,dtype=torch.float32)).squeeze(-1).numpy()*ys
    saved={'state':state,'mean':mu.tolist(),'scale':scale.tolist(),'target_scale':ys,'epoch':best_epoch}
    return predict,saved


def data_arrays():
    data=load_data()
    # Attachment 2 uses interval-end labels: 00:10 is the measured power for
    # [00:00, 00:10), and 0:00+1 is the final [23:50, 24:00) interval.
    # These arrays already cover the natural calendar year and must not be
    # shifted merely to match the contradictory result-template labels.
    load=data.load_kw.reshape(-1)
    pv=data.pv_kw.reshape(-1)
    price=data.price.copy()
    return data,load,pv,price


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--epochs',type=int,default=50)
    args=parser.parse_args();torch.set_num_threads(2);OUT.mkdir(exist_ok=True)
    (OUT/'models').mkdir(exist_ok=True)
    data,load,pv,price=data_arrays()
    xx=[];base=[]
    for day in range(365):
        pairs=[features(data.load_kw[:day],np.zeros_like(data.pv_kw[:day]),date(2025,1,1)+timedelta(days=day),a) for a in (0,1)]
        xx.append(np.concatenate([a[0] for a in pairs]));base.append(np.concatenate([a[1] for a in pairs]))
    xx=np.asarray(xx);base=np.asarray(base)
    # At day zero no load history exists; the reference profile is known input.
    base[0]=np.tile(np.asarray([r[2] for r in list(read_xlsx(ROOT/'C题/附件/附件1.xlsx').values())[0][1:]]),2)
    load_pred=base.copy();load_cut=np.full(365,-1);models=[]
    issue=np.repeat(np.arange(365)*144,288)
    target=(np.arange(365)[:,None]*144+np.arange(288)).reshape(-1)
    x=xx.reshape(-1,xx.shape[-1]); y=np.full(len(target),np.nan)
    valid=target<len(load);y[valid]=load[target[valid]]-base.reshape(-1)[valid]
    cuts=[21]+[(date(2025,m,1)-date(2025,1,1)).days for m in range(2,13)]
    for cut,stop in zip(cuts,cuts[1:]+[365]):
        train=(issue>=7*144)&(target<(cut-7)*144)&np.isfinite(y)
        val=(issue>=(cut-7)*144)&(target<cut*144)&np.isfinite(y)
        predict,saved=fit(x,y,train,val,1700+cut,args.epochs)
        corr=predict(x[val]);choices=[0.,.25,.5,.75,1.]
        alpha=min(choices,key=lambda a:np.mean((y[val]-a*corr)**2))
        load_pred[cut:stop]=np.maximum(0,base[cut:stop]+alpha*predict(xx[cut:stop].reshape(-1,x.shape[1])).reshape(stop-cut,288))
        load_cut[cut:stop]=cut*144
        saved.update(cutoff=cut*144,alpha=alpha,train_max_target=int(target[train].max()),validation_max_target=int(target[val].max()))
        torch.save(saved,OUT/'models'/f'load_{data.dates[cut]}.pt')
        models.append({'kind':'load','cutoff':str(data.dates[cut]),'alpha':alpha,'epoch':saved['epoch']})
        print('load',data.dates[cut],alpha,flush=True)

    rec=forecast_records();raw=np.array([r[3] for r in rec]).reshape(1460,24)
    issued=np.repeat(np.arange(1460)*36,24);leads=np.tile(np.arange(1,25),1460)
    targets=issued+6*leads;hours=(targets/6)%24;season=targets/(144*365.25)*2*np.pi
    repeated=np.repeat(raw,24,axis=0)
    xpv=np.column_stack([raw.reshape(-1),leads/24,np.sin(2*np.pi*hours/24),np.cos(2*np.pi*hours/24),
        np.sin(season),np.cos(season),np.sin(2*np.pi*(issued%144)/144),np.cos(2*np.pi*(issued%144)/144),
        repeated.mean(1),repeated.max(1)]).astype(np.float32)
    # Forecast targets are clock-hour boundaries.  Under the endpoint-label
    # convention, the observation at boundary b is stored in interval b-1.
    ypv=np.full(len(targets),np.nan);m=(targets>=1)&(targets<=len(pv))
    ypv[m]=pv[targets[m]-1]-raw.reshape(-1)[m]
    groups=((issued%144)//36)*4+(leads-1)//6
    def biases(mask):
        sums=np.bincount(groups[mask],weights=ypv[mask],minlength=16)
        counts=np.bincount(groups[mask],minlength=16)
        return sums/(counts+20.)
    calibrated=raw.copy();mean_only=raw.copy();pv_cut=np.full(1460,-1)
    # January cold start: update bias using labels strictly before day midnight.
    for day in range(31):
        mask=(targets<day*144)&np.isfinite(ypv)
        b=biases(mask);sl=slice(day*96,(day+1)*96)
        v=raw[day*4:(day+1)*4]
        calibrated[day*4:(day+1)*4]=np.where(v>0,np.maximum(0,v+b[groups[sl]].reshape(4,24)),0.)
        mean_only[day*4:(day+1)*4]=calibrated[day*4:(day+1)*4]
        pv_cut[day*4:(day+1)*4]=day*144
    for cut,stop in zip(cuts[1:],cuts[2:]+[365]):
        train=(targets<(cut-7)*144)&np.isfinite(ypv)
        val=(issued>=(cut-7)*144)&(targets<cut*144)&np.isfinite(ypv)&(raw.reshape(-1)>0)
        b=biases(train);bv=b[groups[val]]
        shrink=min([0.,.5,1.],key=lambda a:np.mean((ypv[val]-a*bv)**2))
        b*=shrink;sl=slice(cut*96,stop*96);bc=b[groups[sl]]
        correction=bc.copy();alpha=0.;saved=None
        if cut>31:
            predict,saved=fit(xpv,ypv,train&(raw.reshape(-1)>0),val,2700+cut,args.epochs)
            cv=predict(xpv[val]);bv=b[groups[val]]
            gate=time_weight(issued[val]//144)
            scores=[(a,float(np.mean((ypv[val]-(1-a*gate)*bv-a*gate*cv)**2))) for a in [0.,.25,.5,.75,1.]]
            a,score=min(scores,key=lambda z:z[1])
            if score<.99*scores[0][1]:alpha=a
            weight=alpha*time_weight(issued[sl]//144)
            correction=(1-weight)*bc+weight*predict(xpv[sl])
        rr=raw[cut*4:stop*4]
        calibrated[cut*4:stop*4]=np.where(rr>0,np.maximum(0,rr+correction.reshape(-1,24)),0.)
        mean_only[cut*4:stop*4]=np.where(rr>0,np.maximum(0,rr+bc.reshape(-1,24)),0.)
        pv_cut[cut*4:stop*4]=cut*144
        payload=saved or {};payload.update(cutoff=cut*144,gamma=alpha,time_ramp_start_days=31,time_ramp_length_days=90,bias=b.tolist(),bias_shrink=shrink,
            train_max_target=int(targets[train].max()),validation_max_target=int(targets[val].max()))
        torch.save(payload,OUT/'models'/f'pv_{data.dates[cut]}.pt')
        models.append({'kind':'pv','cutoff':str(data.dates[cut]),'gamma':alpha,'bias_shrink':shrink,
            'mlp_weight_first_day':float(alpha*time_weight(cut)),
            'mlp_weight_last_day':float(alpha*time_weight(stop-1))})
        print('pv',data.dates[cut],alpha,flush=True)

    # Archive predictions at issue time, before any scenario errors are formed.
    net=np.empty((1460,144));net_raw=np.empty_like(net);net_bias=np.empty_like(net)
    for k in range(1460):
        day=k//4;start=k*36;offset=(k%4)*36
        pred_l=load_pred[day,offset:offset+144]
        # The preceding endpoint is observable at issue time.  Jan 1 00:00
        # has no earlier measurement in Attachment 2, and PV is set to zero.
        anchor_p=0. if start==0 else pv[start-1]
        for source,dest in [(calibrated,net),(raw,net_raw),(mean_only,net_bias)]:
            pv_nodes=np.interp(np.arange(145),np.arange(0,145,6),np.r_[anchor_p,source[k]])
            dest[k]=pred_l-pv_nodes[:-1]
    truth=load-pv
    errors=np.full_like(net,np.nan)
    for k in range(1460):
        length=min(144,len(truth)-k*36)
        errors[k,:length]=truth[k*36:k*36+length]-net[k,:length]
    evaluation=(issued>=31*144)&np.isfinite(ypv)
    metrics={}
    for name,pred in [('raw',raw),('bias',mean_only),('adaptive',calibrated)]:
        err=ypv[evaluation]-(pred.reshape(-1)-raw.reshape(-1))[evaluation]
        metrics[name]={'mae_kw':float(np.abs(err).mean()),'rmse_kw':float(np.sqrt(np.mean(err**2)))}
    np.savez_compressed(OUT/'forecasts.npz',net=net,net_raw=net_raw,net_bias=net_bias,errors=errors,
        load=load_pred,raw=raw,calibrated=calibrated,load_cut=load_cut,pv_cut=pv_cut,price=price)
    (OUT/'forecast_report.json').write_text(json.dumps({'models':models,'pv_metrics':metrics,
        'missing_future_labels':int((~m).sum()),'cutoff_rule':'target timestamp < fit cutoff',
        'night_rule':'zero official hourly forecast stays zero after calibration'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(metrics,flush=True)


if __name__=='__main__':main()

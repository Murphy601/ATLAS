import sys; sys.path.insert(0,"src")
import numpy as np, solve as SV, json
def facts(r):
    rows,L=SV.summarise(r); c=SV.check_path(r)
    lb={}
    for a,b in zip(rows[:-1],rows[1:]):
        d=b["chainage_m"]-a["chainage_m"]
        for x in (a,b): lb[x["landcover"]]=lb.get(x["landcover"],0)+d/2
    xw=[x for x in rows if x["landcover"]=="Watercourse"]
    top=max(rows,key=lambda x:x["northing"])
    P=np.array([(x["easting"],x["northing"]) for x in rows])
    return dict(total=r["cost"],constr=rows[-1]["cum_constr_usd"],haul=rows[-1]["cum_haul_usd"],L=L,n=len(rows),
                ndef=c["n_deflections"],wood=lb.get("Woodland",0),grass=lb.get("Grassland / pasture",0),
                crop=lb.get("Cultivated cropland",0),track=lb.get("Existing gravel track",0),
                end=tuple(P[-1]),ch_x=xw[0]["chainage_m"],ch_top=top["chainage_m"],adv=c["max_adverse_loaded"],
                mink=c["min_k"],rise=c["max_rise"]), P
tol=dict(total=("rel",1e-4),constr=("rel",1e-4),haul=("rel",5e-3),L=("abs",1.0),n=("abs",0),ndef=("abs",0),
         wood=("rel",0.01),grass=("rel",0.005),crop=("rel",0.01),track=("rel",0.01),end=("pt",1.0),ch_x=("abs",1.0),
         ch_top=("abs",1.0),adv=("abs",0.02),mink=("abs",0.005),rise=("abs",0.02))
def same(k,a,b):
    m,t=tol[k]
    if m=="rel": return abs(a-b)<=t*abs(b)
    if m=="abs": return abs(a-b)<=t+1e-9
    return max(abs(a[0]-b[0]),abs(a[1]-b[1]))<=t
g,PG=facts(SV.solve({}))
print({k:(round(v,3) if isinstance(v,float) else v) for k,v in g.items()})
out={}
for name in ["no_adverse","no_vc","no_radius","radius_single","no_haul","haul_flip","end_revc","end_intl","revC_rules","no_turn","no_sustain","no_heritage"]:
    r=SV.solve(SV.VARIANTS[name]); f,P=facts(r)
    diff=[k for k in g if not same(k,f[k],g[k])]
    # golden vertices not within 5 m of variant path
    d=np.array([np.hypot(*(P-p).T).min() for p in PG])
    out[name]=np.nonzero(d>5)[0].tolist()
    print(f"{name:14s} differs: {' '.join(diff)}   golden-only vertices: {len(out[name])}")
json.dump(dict(out=out,PG=PG.tolist()),open("work/facts.json","w"))

import sys, itertools; sys.path.insert(0,"src")
import numpy as np, solve as SV
def P(o):
    r=SV.solve(o)
    if r is None: return None, None
    rows,_=SV.summarise(r); return np.array([(x["easting"],x["northing"]) for x in rows]), r["cost"]
def div(PG,Pv):
    if Pv is None: return -1
    d=np.array([np.hypot(*(Pv-p).T).min() for p in PG]); return int((d>0.5).sum())
for R,adv,hc in [(45.0,6.0,6000.0),(45.0,6.0,10000.0),(45.0,6.0,12000.0),(50.0,6.0,8000.0),(45.0,5.5,8000.0),(40.0,6.0,8000.0)]:
    base=dict(radius=R,adv_max=adv,haul_c=hc)
    PG,c=P(base)
    if PG is None: print(R,adv,hc,"golden NO PATH"); continue
    out=[]
    for nm,o in (("adv",{"no_adverse":True}),("vc",{"no_vc":True}),("rad",{"no_tangent":True}),("rad1",{"tan_single":True}),("haul",{"no_haul":True})):
        out.append(f"{nm}={div(PG,P(dict(base,**o))[0])}")
    print(R,adv,hc,f"golden ${c:,.0f} n={len(PG)}"," ".join(out),flush=True)

import sys; sys.path.insert(0,"work"); sys.path.insert(0,"src")
import numpy as np
from scan import show, SV
def P(r):
    rows,_=SV.summarise(r); return np.array([(x["easting"],x["northing"]) for x in rows])
for thr in (1.0, 2.0, 3.0):
    for hc in (8000.0, 15000.0):
        g=show(f"thr{thr} hc{hc}", {"haul_thr":thr,"haul_c":hc}); PG=P(g)
        for nm,o in (("flip",{"haul_flip":True}),("linear",{"haul_thr":0.0}),("noRR",{"haul_thr":thr+3}),("nohaul",{"no_haul":True}),("noadv",{"no_adverse":True}),("novc",{"no_vc":True}),("norad",{"no_tangent":True})):
            r=SV.solve(dict({"haul_thr":thr,"haul_c":hc},**o))
            if r is None: print("   ",nm,"NO PATH"); continue
            Pv=P(r); d=np.array([np.hypot(*(Pv-p).T).min() for p in PG]); print(f"    {nm:7s} ${r['cost']:,.0f} div={int((d>0.5).sum())}")

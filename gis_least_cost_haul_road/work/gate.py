import sys; sys.path.insert(0,"src")
import numpy as np, solve as SV
from pyproj import Transformer
t=Transformer.from_crs(32614,2277,always_xy=True); tb=Transformer.from_crs(2277,32614,always_xy=True)
orig=SV.build_cost
def P(r):
    rows,_=SV.summarise(r); return np.array([(x["easting"],x["northing"]) for x in rows])
for g in [(586404.9,3349902.5),(586454.9,3350102.5),(586214.9,3350602.5),(586504.9,3350502.5)]:
    E,N=t.transform(*g); SV.BRIEF["g1_surface_ftus"]=[E*1.00012,N*1.00012]
    r=SV.solve({})
    if r is None: print(g,"NO PATH"); continue
    PG=P(r); rows,L=SV.summarise(r)
    out=[f"gold ${r['cost']:,.0f} L={L:,.0f}"]
    for nm in ["end_revc","end_nosaf","end_intl","no_vc","no_adverse","no_radius","no_haul","haul_linear","no_turn","no_sustain","no_heritage"]:
        rr=SV.solve(SV.VARIANTS[nm])
        if rr is None: out.append(f"{nm}=NOPATH"); continue
        Pv=P(rr); d=np.array([np.hypot(*(Pv-p).T).min() for p in PG]); out.append(f"{nm}={int((d>0.5).sum())}")
    print(g," ".join(out),flush=True)

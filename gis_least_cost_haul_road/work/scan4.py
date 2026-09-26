import sys; sys.path.insert(0,"work"); sys.path.insert(0,"src")
import numpy as np, sitedef as S
from scan import show, SV
d=float(120/450*np.cos(880/450)); b2=(np.degrees(np.arctan2(d,1.0)))%360
print("X2 bearing", b2)
SV.BRIEF["channel_bearing"]={"X1":0.0,"X2":b2}
base={"adv_max":6.0,"radius":45.0,"vc_k":1.4}
show("ALL", base)
for sk in (30.0, 45.0):
    show(f"ALL skew{sk}", dict(base, skew_max=sk)); show(f"ALL skew{sk} NS", dict(base, skew_max=sk, skew_ns=True))
for hc in (1500.0, 3000.0, 5000.0):
    show(f"ALL haul{hc}", dict(base, haul_c=hc)); show(f"ALL haul{hc} flip", dict(base, haul_c=hc, haul_flip=True))

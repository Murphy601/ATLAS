import sys; sys.path.insert(0,"work")
from scan import show
for k in (1.4, 1.5, 1.7, 2.0):
    show(f"K {k}", {"vc_k": k})
base={"adv_max":6.0,"radius":45.0}
for k in (1.2,1.3,1.4,1.5):
    show(f"ALL K{k}", dict(base, vc_k=k))

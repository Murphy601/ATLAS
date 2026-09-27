import sys; sys.path.insert(0,"src")
from scan import show
for v in (50.0, 20.0, 12.0, 10.0, 8.0):
    show(f"vc {v}", {"vc_max": v})
for a in (7.5, 8.0, 8.5):
    show(f"adv {a}", {"adv_max": a}); show(f"adv {a} flip", {"adv_max": a, "adv_flip": True})

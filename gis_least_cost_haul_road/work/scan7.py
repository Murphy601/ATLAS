import sys; sys.path.insert(0,"work")
from scan import show, SV
for o in ({"vc_k":1.39},{"vc_k":1.41},{"adv_max":5.98},{"adv_max":6.02},{"radius":44.0},{"radius":46.0},
          {"haul_c":2990.0},{"haul_c":3010.0},{"intl_ft":True,"rev_order":True}):
    show(str(o), o)

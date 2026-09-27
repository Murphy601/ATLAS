import sys; sys.path.insert(0,"work")
from scan import show, SV
show("X1 nowidth", {"drop_X2":True,"no_width":True})
show("X1 nowidth nohaul", {"drop_X2":True,"no_width":True,"no_haul":True})
show("X1 nowidth noradius", {"drop_X2":True,"no_width":True,"no_tangent":True})
show("X1 nowidth noadv", {"drop_X2":True,"no_width":True,"no_adverse":True})
show("X1 nowidth novc", {"drop_X2":True,"no_width":True,"no_vc":True})

import sys; sys.path.insert(0,"src")
import numpy as np, solve as SV
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
V=["golden","no_haul","no_adverse","no_radius","no_vc","revC_rules","no_turn","no_heritage","no_sustain"]
fig,ax=plt.subplots(figsize=(16,12))
r0=SV.solve({})
ax.contour(r0["EX"],r0["EY"],r0["z"],levels=40,colors="grey",linewidths=0.3)
ax.imshow(np.where(r0["lcd"]==6,1,np.where(r0["lcd"]==7,2,0)),extent=[583000,586600,3348700,3351500],cmap="Blues",alpha=0.4)
for k in V:
    r=SV.solve(SV.VARIANTS[k]); rows,L=SV.summarise(r)
    p=np.array([(x["easting"],x["northing"]) for x in rows])
    ax.plot(p[:,0],p[:,1],lw=2.5 if k=="golden" else 1.2,label=f"{k} {r['cost']:,.0f} constr {rows[-1]['cum_constr_usd']:,.0f} haul {rows[-1]['cum_haul_usd']:,.0f}")
    if k=="golden":
        print("constr",rows[-1]["cum_constr_usd"],"haul",rows[-1]["cum_haul_usd"],"rise loaded",rows[-1]["cum_haul_usd"]/3000, "end", rows[-1]["easting"], rows[-1]["northing"])
ax.legend(fontsize=8); ax.set_aspect("equal"); fig.savefig("work/vars.png",dpi=70)

import sys; sys.path.insert(0,"src")
import numpy as np, solve as SV
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
b=SV.BRIEF
vc=float(sys.argv[1])
z,lcd,EX,EY,base,pts,mok=SV.build_cost({})
st,nxt=SV.run_states(b["steep_run_max"],10.0)
si,sj=SV.cell_of(pts["START"])
end,dist,prev=SV._dijkstra(z,base,mok,SV.DIRS,SV.DLEN,10.0,10.0,8.0,True,True,nxt,len(st),si,sj,-1,-1,False,0,0.0,vc,0.0,1)
ny,nx=z.shape
d=dist.reshape(ny,nx,-1).min(-1)
R=np.isfinite(d)
print("reachable",R.sum(),"of",np.isfinite(base).sum())
ei,ej=SV.cell_of(pts["END"]); print("end reach",R[ei,ej])
fig,ax=plt.subplots(figsize=(12,9))
ax.imshow(np.where(R,1,0)+np.where(np.isfinite(base),0,2),origin="upper")
ax.contour(z,levels=30,colors="w",linewidths=0.3)
fig.savefig(f"work/reach_{vc}.png",dpi=80)

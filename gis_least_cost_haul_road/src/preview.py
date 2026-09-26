import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

import solve as SV

ROOT = Path(__file__).resolve().parent.parent
variants = {"golden": {}, "no_setback": {"no_setback": True}, "no_heritage": {"no_heritage": True},
            "water": {"water_passable": True}, "iso": {"isotropic": True}}
fig, ax = plt.subplots(figsize=(14, 11))
r0 = SV.solve({})
z, lcd, EX, EY = r0["z"], r0["lcd"], r0["EX"], r0["EY"]
b = SV.BRIEF
rgb = np.zeros(lcd.shape + (3,))
for c, info in b["classes"].items():
    rgb[lcd == int(c)] = np.array(info["rgb"]) / 255
ext = [EX.min() - 5, EX.max() + 5, EY.min() - 5, EY.max() + 5]
ax.imshow(rgb, extent=ext, origin="upper")
ax.imshow(np.isnan(r0["base"]), extent=ext, origin="upper", cmap="Greys", alpha=0.25)
cs = ax.contour(EX, EY, z, levels=np.arange(350, 520, 5), colors="k", linewidths=0.3)
ax.clabel(cs, cs.levels[::4], fontsize=6)
cols = ["red", "magenta", "orange", "cyan", "black"]
for (name, o), c in zip(variants.items(), cols):
    r = r0 if name == "golden" else SV.solve(o)
    if r is None:
        continue
    p = np.array([(EX[i, j], EY[i, j]) for i, j in r["path"]])
    ax.plot(p[:, 0], p[:, 1], color=c, lw=1.6, label=f"{name} ${r['cost']:,.0f}")
for k, (e, n) in r0["pts"].items():
    ax.plot(e, n, "k^"); ax.annotate(k, (e, n))
ax.legend()
fig.savefig(ROOT / "work" / "preview.png", dpi=110)

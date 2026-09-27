import sys, time
sys.path.insert(0, "src")
import solve as SV


def show(name, o):
    t = time.time()
    r = SV.solve(o)
    if r is None:
        print(f"{name:34s} NO PATH ({time.time()-t:.0f}s)", flush=True); return None
    rows, L = SV.summarise(r); c = SV.check_path(r)
    print(f"{name:34s} ${r['cost']:,.0f} L={L:,.1f} n={len(rows)} adv={c['max_adverse_loaded']:.2f} "
          f"dg={c['max_grade_change']:.2f} K={c['min_k']:.2f} tan={c['min_tangent']:.1f}/{c['start_tangent']:.0f}/{c['end_tangent']:.0f} "
          f"run={c['max_steep_run']:.1f} {SV.xing(rows)} Nmax={max(x['northing'] for x in rows):.0f} ({time.time()-t:.0f}s)", flush=True)
    return r


if __name__ == "__main__":
    show("revC", {})
    for k in (0.9, 1.0, 1.1, 1.2, 1.3):
        show(f"K {k}", {"vc_k": k})
    for R in (40.0, 45.0, 55.0):
        show(f"R {R}", {"radius": R})

"""afcfd CLI: geometry / case / run / sweep / post / acoustics。

`uv run afcfd <subcommand> ...` で起動する。OpenFOAM 本体は VM 内、ここはホスト側の制御・前後処理。
"""
from __future__ import annotations

import argparse
import csv
import os


def _cmd_geometry(a):
    from airfoil_cfd import geometry
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    out = geometry.build(airfoil=a.airfoil, dat=a.dat, chord=a.chord, points=a.points,
                         mode=a.mode, span=a.span, cap_tip=a.cap_tip, out=a.out)
    print(f"STL を生成: {out}")


def _cmd_case(a):
    from airfoil_cfd import case
    cdir = case.clone_case(a.name, stl_src=a.stl or None)
    case.set_turbulence(cdir, a.turb)
    case.set_inlet_velocity(cdir, a.U, a.alpha, chord=a.chord, span=a.span)
    print(f"ケース作成: {cdir} (turb={a.turb}, U={a.U}, alpha={a.alpha})")


def _cmd_run(a):
    from airfoil_cfd import case
    rel = os.path.join("cases", "runs", a.name)
    if a.mesh:
        case.mesh(rel)
    case.run(rel, a.np)


def _cmd_sweep(a):
    from airfoil_cfd import case, postprocess
    res = case.continuous_sweep(a.case_base, a.alpha_up, a.alpha_down, a.U,
                                turb=a.turb, parallel_np=a.np)
    rows = []
    for direction, alpha, rel in res:
        cdir = os.path.join(case.REPO, rel)
        try:
            s = postprocess.force_summary(cdir, transient=(a.turb == "les"))
            rows.append([direction, alpha, s.get("Cl"), s.get("Cd")])
        except Exception as e:  # noqa: BLE001
            rows.append([direction, alpha, None, None])
            print(f"warn: {rel}: {e}")
    out = os.path.join(case.REPO, "cases", "runs", f"{a.case_base}_sweep_results.csv")
    with open(out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["dir", "alpha", "Cl", "Cd"]); w.writerows(rows)
    print(f"掃引結果: {out}")


def _cmd_post(a):
    from airfoil_cfd import postprocess
    cdir = os.path.join("cases", "runs", a.case) if not os.path.isdir(a.case) else a.case
    aref = getattr(a, "aref", None)
    lref = getattr(a, "lref", None)
    if a.cp:
        out = a.out or "docs/figures/cp.png"
        print(postprocess.plot_cp(cdir, a.U, out, alpha_deg=getattr(a, "alpha", 0.0)))
    if a.vortex:
        print(postprocess.visualize_vortex(cdir, method=a.vortex, iso=a.iso,
                                            out=a.out or "docs/figures/vortex.png"))
    if a.coeffs:
        s = postprocess.force_summary(cdir, transient=a.transient, aref=aref, lref=lref)
        for k, v in s.items():
            print(f"  {k}: {v:.6f}")
    if getattr(a, "convergence", False):
        out = a.out or "docs/figures/convergence.png"
        print(postprocess.plot_convergence(cdir, out, aref=aref, lref=lref))


def _cmd_acoustics(a):
    from airfoil_cfd import acoustics
    cdir = os.path.join("cases", "runs", a.case) if not os.path.isdir(a.case) else a.case
    print(acoustics.plot_spl(cdir, a.U, a.ref_len, a.out or "docs/figures/spl.png",
                             probe=a.probe))


def main(argv=None):
    p = argparse.ArgumentParser(prog="afcfd", description="OpenFOAM13 翼型CFD 制御/前後処理")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("geometry", help="翼型STL生成")
    g.add_argument("--airfoil"); g.add_argument("--dat")
    g.add_argument("--chord", type=float, default=1.0); g.add_argument("--points", type=int, default=200)
    g.add_argument("--mode", choices=["2d", "3d-infinite", "3d-finite"], default="2d")
    g.add_argument("--span", type=float, default=None); g.add_argument("--cap-tip", action="store_true")
    g.add_argument("--out", default="airfoil.stl"); g.set_defaults(func=_cmd_geometry)

    c = sub.add_parser("case", help="ケース生成")
    c.add_argument("--name", required=True); c.add_argument("--turb", choices=["rans", "les"], default="rans")
    c.add_argument("--U", type=float, default=30.0); c.add_argument("--alpha", type=float, default=0.0)
    c.add_argument("--stl", default=None, help="翼型STLパス(省略時はtemplateのSTLを使用)")
    c.add_argument("--chord", type=float, default=1.0); c.add_argument("--span", type=float, default=0.01)
    c.set_defaults(func=_cmd_case)

    r = sub.add_parser("run", help="メッシュ/計算をVMで実行")
    r.add_argument("--name", required=True); r.add_argument("--mesh", action="store_true")
    r.add_argument("--np", type=int, default=0); r.set_defaults(func=_cmd_run)

    s = sub.add_parser("sweep", help="迎角連続掃引(ヒステリシス)")
    s.add_argument("--case-base", required=True)
    s.add_argument("--alpha-up", default="0:18:1"); s.add_argument("--alpha-down", default="18:0:1")
    s.add_argument("--U", type=float, default=30.0); s.add_argument("--turb", choices=["rans", "les"], default="rans")
    s.add_argument("--np", type=int, default=0); s.set_defaults(func=_cmd_sweep)

    po = sub.add_parser("post", help="後処理(Cl/Cd, Cp, 渦)")
    po.add_argument("--case", required=True); po.add_argument("--U", type=float, default=30.0)
    po.add_argument("--alpha", type=float, default=0.0, help="迎角 [deg] (Cp タイトル用)")
    po.add_argument("--aref", type=float, default=None, help="正規化面積 [m²] (ファイルと異なる場合)")
    po.add_argument("--lref", type=float, default=None, help="参照弦長 [m] (ファイルと異なる場合)")
    po.add_argument("--cp", action="store_true"); po.add_argument("--coeffs", action="store_true")
    po.add_argument("--convergence", action="store_true", help="Cl/Cd 収束履歴プロット")
    po.add_argument("--transient", action="store_true")
    po.add_argument("--vortex", choices=["q", "lambda2", "vorticity"])
    po.add_argument("--iso", type=float, default=50.0); po.add_argument("--out")
    po.set_defaults(func=_cmd_post)

    ac = sub.add_parser("acoustics", help="空力騒音(Curle/FFT/SPL)")
    ac.add_argument("--case", required=True); ac.add_argument("--U", type=float, default=30.0)
    ac.add_argument("--ref-len", type=float, default=1.0); ac.add_argument("--probe", type=int, default=0)
    ac.add_argument("--method", choices=["curle", "fft"], default="fft"); ac.add_argument("--out")
    ac.set_defaults(func=_cmd_acoustics)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

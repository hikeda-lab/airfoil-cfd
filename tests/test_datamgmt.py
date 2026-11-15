"""データ管理（run メタデータ・保存レベル選択・保存先チェック）のテスト。合成ケースで検証する。"""
import os

import pytest

from airfoil_cfd.datamgmt import config as C
from airfoil_cfd.datamgmt import destination as D
from airfoil_cfd.datamgmt import meta as M
from airfoil_cfd.datamgmt import registry as R
from airfoil_cfd.datamgmt import tiers as T

HDR = "FoamFile { format ascii; class dictionary; object x; }\n"


def _w(path, text="x", size=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text if size is None else "0" * size)


def make_case(root, name="naca0012_les_test", les=True, decomposed_missing=()):
    c = os.path.join(root, "cases", "runs", name)
    _w(f"{c}/system/controlDict", HDR + "solver incompressibleFluid;\ndeltaT 1e-4;\n"
       "endTime 0.4;\nwriteInterval 0.1;\nadjustTimeStep yes;\nmaxCo 0.8;\n")
    sim = "LES;\nLES { model WALE; delta cubeRootVol; }" if les else "RAS;\nRAS { model kOmegaSST; }"
    _w(f"{c}/constant/momentumTransport", HDR + f"simulationType {sim}\n")
    _w(f"{c}/constant/physicalProperties", HDR + "viscosityModel constant;\n"
       "nu [0 2 -1 0 0 0 0] 1.5e-05;\n")
    _w(f"{c}/constant/polyMesh/owner", HDR.replace("object x;", 'note "nPoints:10 nCells:4 '
       'nFaces:20 nInternalFaces:4"; object owner;'), )
    _w(f"{c}/constant/polyMesh/boundary", "front { type empty; }\nwing { type wall; }\n")
    _w(f"{c}/0/U", HDR + "internalField uniform (29.708042 4.175193 0);\nboundaryField\n{\n"
       "    inlet { type fixedValue; value uniform (29.708042 4.175193 0); }\n}\n")
    for t in ("0.1", "0.2", "0.3", "0.4"):
        for fld in ("U", "p", "nut"):
            _w(f"{c}/{t}/{fld}", size=1000)
    if les:
        _w(f"{c}/0.4/UMean", size=1000)
        _w(f"{c}/0.4/UPrime2Mean", size=2000)
    _w(f"{c}/log.foamRun", "  \\\\  /    A nd           | Version:  13\nBuild  : 13-abc\n"
       "Exec   : foamRun\nDate   : Aug 07 2026\nTime   : 03:18:16\nHost   : \"openfoam\"\n"
       "nProcs : 1\n\nTime = 0.4s\n\nEnd\n")
    fc = f"{c}/postProcessing/forceCoeffs/0/forceCoeffs.dat"
    rows = "\n".join(f"{i*0.01:.2f}\t0.01\t0.02\t0.8" for i in range(1, 41))
    _w(fc, "# magUInf       : 3.0e+01\n# lRef          : 1.0\n# Aref          : 1.0\n"
       "# Time\tCm\tCd\tCl\n" + rows + "\n")
    for t in ("0.1", "0.2", "0.3", "0.4"):
        _w(f"{c}/postProcessing/surfaces/{t}/airfoil.xy", size=500)
    _w(f"{c}/VTK/x.vtk", size=5000)
    for i in (0, 1):
        _w(f"{c}/processor{i}/constant/polyMesh/owner", size=100)
        for t in ("0.4", *decomposed_missing):
            _w(f"{c}/processor{i}/{t}/U", size=300)
    return c


@pytest.fixture()
def env(tmp_path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    src = os.path.join(C.CONFIG_DIR, "archive.yaml")
    (repo / "config" / "archive.yaml").write_text(open(src).read())
    mount = tmp_path / "HDD"
    cfg = C.load(str(repo / "config"), local_override={
        "destination": {"mount": str(mount), "volume_uuid": None}, "mirrors": []})
    cfg.repo = str(repo)
    return cfg, str(repo), str(mount)


def test_glob_regex():
    r = T.glob_to_regex("constant/*")
    assert r.match("constant/momentumTransport") and not r.match("constant/polyMesh/owner")
    r = T.glob_to_regex("postProcessing/forceCoeffs*/**")
    assert r.match("postProcessing/forceCoeffs/0/forceCoeffs.dat")
    assert T.glob_to_regex("**/.DS_Store").match(".DS_Store")


def test_extract_meta(env):
    cfg, repo, _ = env
    c = make_case(repo)
    m = M.extract(c, repo)
    assert m["turbulence"] == {"simulationType": "LES", "model": "WALE", "delta": "cubeRootVol"}
    assert m["physics"]["alpha_deg"] == pytest.approx(8.0, abs=1e-3)
    assert m["physics"]["Re"] == 2_000_000
    assert m["time"]["deltaT"] == 1e-4 and m["time"]["latest_time"] == "0.4"
    assert m["openfoam"]["build"] == "13-abc"
    assert m["mesh"]["cells"] == 4 and m["mesh"]["dimension"] == "2D"
    assert m["created"] == "2026-08-07T03:18:16"
    assert m["run_id"].startswith("20260807-031816_naca0012-les-test_")
    assert m["results"]["Cl"] == pytest.approx(0.8)
    assert M.extract(c, repo)["run_id"] == m["run_id"]   # 再抽出で ID が変わらない


def test_tiers_nested_and_les_options(env):
    cfg, repo, _ = env
    c = make_case(repo)
    m = M.extract(c, repo)
    s = {n: T.select(c, m, t, cfg) for n, t in cfg.tiers.items()}
    arcs = {n: {e.arc for e in sel.selected} for n, sel in s.items()}
    assert arcs["minimal"] <= arcs["standard"] <= arcs["full"]
    assert "constant/polyMesh/owner" not in arcs["minimal"]
    assert "postProcessing/forceCoeffs/0/forceCoeffs.dat" in arcs["minimal"]
    assert {"0.4/UMean", "0.4/UPrime2Mean", "constant/polyMesh/owner"} <= arcs["standard"]
    assert "postProcessing/surfaces/0.4/airfoil.xy" in arcs["standard"]
    assert "postProcessing/surfaces/0.1/airfoil.xy" not in arcs["standard"]
    assert not any(a.startswith(("VTK/", "processor")) for a in arcs["full"])   # reconstruct 済み
    assert s["standard"].snapshot_times   # LES は代表瞬時場を自動選択
    # LES オプション
    o = T.Options(mean=False, rms=False, snapshots=[], acoustic_series=True)
    a = {e.arc for e in T.select(c, m, cfg.tiers["standard"], cfg, o).selected}
    assert "0.4/UMean" not in a and "0.4/UPrime2Mean" not in a and "0.4/U" in a
    assert "0.2/U" not in a and "postProcessing/surfaces/0.1/airfoil.xy" in a
    v = {e.arc for e in T.select(c, m, cfg.tiers["full"], cfg, T.Options(include_vtk=True)).selected}
    assert "VTK/x.vtk" in v


def test_unreconstructed_times_kept_in_full(env):
    cfg, repo, _ = env
    c = make_case(repo, decomposed_missing=("0.05",))
    m = M.extract(c, repo)
    full = T.select(c, m, cfg.tiers["full"], cfg)
    arcs = {e.arc for e in full.selected}
    assert "processor0/0.05/U" in arcs and "processor1/constant/polyMesh/owner" in arcs
    assert "processor0/0.4/U" not in arcs                 # reconstruct 済みの時刻は重複なので除外
    std = T.select(c, m, cfg.tiers["standard"], cfg)
    assert any("processor*" in w for w in std.warnings)


def test_full_catch_all_but_not_regenerable(env):
    cfg, repo, _ = env
    c = make_case(repo, les=False)
    _w(f"{c}/notes.txt", "memo")
    _w(f"{c}/dynamicCode/lib.so", size=100)
    _w(f"{c}/inner/system/controlDict", HDR)
    m = M.extract(c, repo)
    full = T.select(c, m, cfg.tiers["full"], cfg)
    arcs = {e.arc for e in full.selected}
    assert "notes.txt" in arcs
    assert not any(a.startswith(("dynamicCode/", "inner/")) for a in arcs)
    assert any("inner/" in w for w in full.warnings)
    assert "notes.txt" not in {e.arc for e in T.select(c, m, cfg.tiers["standard"], cfg).selected}


def test_selection_is_read_only(env):
    cfg, repo, _ = env
    c = make_case(repo)
    before = {os.path.join(d, f): os.stat(os.path.join(d, f)).st_mtime_ns
              for d, _, fs in os.walk(c) for f in fs}
    m = M.extract(c, repo)
    for t in cfg.tiers.values():
        T.select(c, m, t, cfg)
    after = {os.path.join(d, f): os.stat(os.path.join(d, f)).st_mtime_ns
             for d, _, fs in os.walk(c) for f in fs}
    assert before == after


def test_destination_missing_fails(env):
    cfg, _, mount = env
    st = D.check(cfg, 10)
    assert not st.ok and "接続されていません" in st.problems[0]
    os.makedirs(mount)   # ディレクトリはあるがマウントポイントではない
    st = D.check(cfg, 10)
    assert not st.ok and "マウントポイントではありません" in st.problems[0]


def test_registry_roundtrip_and_search(env):
    cfg, repo, _ = env
    c = make_case(repo)
    m = R.build(c, cfg, notes="first")
    m["extra"] = {"rpm": 1000}
    R.write(m, c, cfg)
    again = R.build(c, cfg)                     # 再登録で notes/extra を保持
    assert again["run_id"] == m["run_id"] and again["notes"] == "first"
    assert again["extra"] == {"rpm": 1000}
    assert R.resolve(cfg, "naca0012_les_test")["run_id"] == m["run_id"]
    assert R.resolve(cfg, m["run_id"][:12])["run_id"] == m["run_id"]
    run = R.all_runs(cfg)[0]
    assert R.matches(run, ["turbulence.simulationType=les", "physics.alpha_deg>=7.5"])
    assert not R.matches(run, ["physics.alpha_deg>10"])
    assert R.matches(run, [], text="wale")


# --------------------------------------------------------------------------- #
# push / verify（tmp ディレクトリを HDD 代わりに使う）
# --------------------------------------------------------------------------- #
from airfoil_cfd.datamgmt import archive as A  # noqa: E402


@pytest.fixture()
def hdd_env(tmp_path):
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config" / "archive.yaml").write_text(open(os.path.join(C.CONFIG_DIR, "archive.yaml")).read())
    mount, mirror = tmp_path / "HDD", tmp_path / "mirror"
    mount.mkdir()
    cfg = C.load(str(repo / "config"), local_override={
        "destination": {"mount": str(mount), "volume_uuid": None, "require_mountpoint": False},
        "mirrors": [str(mirror)]})
    cfg.repo = str(repo)
    c = make_case(str(repo))
    m = R.build(c, cfg)
    R.write(m, c, cfg)
    return cfg, c, m, str(mount), str(mirror)


def _snapshot(case):
    return {os.path.join(d, f): (os.stat(os.path.join(d, f)).st_mtime_ns, A.sha256_file(os.path.join(d, f)))
            for d, _, fs in os.walk(case) for f in fs if f != "run.yaml"}


def test_push_requires_init_and_dry_run_writes_nothing(hdd_env):
    cfg, c, m, mount, mirror = hdd_env
    with pytest.raises(A.DestinationUnavailable):
        A.push(cfg, m, c, "standard", T.Options(), execute=True, log=lambda *_: None)
    A.init(cfg, execute=True)
    A.push(cfg, m, c, "standard", T.Options(), execute=False, log=lambda *_: None)
    assert os.listdir(os.path.join(cfg.archive_root, "runs")) == []
    assert not os.path.exists(mirror)


def test_push_verify_roundtrip(hdd_env):
    cfg, c, m, mount, mirror = hdd_env
    A.init(cfg, execute=True)
    before = _snapshot(c)
    meta = A.push(cfg, m, c, "standard", T.Options(), execute=True, log=lambda *_: None)
    assert _snapshot(c) == before                           # 元データは不変・削除なし
    hdd = os.path.join(cfg.archive_root, "runs", m["run_id"])
    assert os.path.isfile(os.path.join(hdd, "data", "0.4", "UMean"))
    assert os.path.isfile(os.path.join(hdd, "run.yaml"))
    assert os.listdir(os.path.join(cfg.archive_root, "staging")) == []
    kinds = {(x["kind"], x["tier"]) for x in meta["archive"]["copies"]}
    assert kinds == {("hdd", "standard"), ("mirror", "minimal")}
    assert R.read_yaml(R.registry_path(cfg, m["run_id"]))["status"] == "archived"
    assert A.verify(cfg, meta, log=lambda *_: None)
    # 保存先の 1 バイト改変を検出する
    target = os.path.join(hdd, "data", "0.4", "U")
    with open(target, "r+b") as f:
        f.write(b"1")
    assert not A.verify(cfg, meta, log=lambda *_: None)


def test_push_fails_when_hdd_unplugged(hdd_env, tmp_path):
    cfg, c, m, mount, mirror = hdd_env
    A.init(cfg, execute=True)
    before = _snapshot(c)
    os.rename(mount, str(tmp_path / "unplugged"))           # 取り外しを模擬
    with pytest.raises(A.DestinationUnavailable) as ei:
        A.push(cfg, m, c, "full", T.Options(), execute=True, log=lambda *_: None)
    assert ei.value.exit_code == 2
    assert _snapshot(c) == before and not os.path.exists(mirror)


def test_leftover_partial_blocks_push(hdd_env):
    cfg, c, m, mount, mirror = hdd_env
    A.init(cfg, execute=True)
    os.makedirs(os.path.join(cfg.archive_root, "staging", f"{m['run_id']}.partial"))
    with pytest.raises(A.ArchiveError, match="未完了コピー"):
        A.push(cfg, m, c, "minimal", T.Options(), execute=True, mirror=False, log=lambda *_: None)


def test_repush_supersedes_without_deleting(hdd_env):
    cfg, c, m, mount, mirror = hdd_env
    A.init(cfg, execute=True)
    meta = A.push(cfg, m, c, "minimal", T.Options(), execute=True, mirror=False, log=lambda *_: None)
    meta = A.push(cfg, meta, c, "full", T.Options(), execute=True, mirror=False, log=lambda *_: None)
    runs = os.listdir(os.path.join(cfg.archive_root, "runs"))
    assert m["run_id"] in runs and any(".superseded-" in r for r in runs)
    assert [x["tier"] for x in meta["archive"]["copies"] if x["kind"] == "hdd"] == ["full"]

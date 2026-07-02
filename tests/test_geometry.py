"""ジオメトリ生成の最小テスト。"""
import numpy as np
from airfoil_cfd import geometry


def test_naca0012_symmetric():
    upper, lower = geometry.naca4("0012", n=80, chord=1.0)
    # 対称翼: 上下面の y が概ね符号反転
    assert np.allclose(upper[:, 1], -lower[:, 1], atol=1e-6)
    # 最大厚みが ~12% 付近
    assert abs(2 * upper[:, 1].max() - 0.12) < 0.02


def test_naca2412_cambered():
    upper, lower = geometry.naca4("2412", n=80, chord=1.0)
    assert upper[:, 1].max() > 0          # キャンバで上面が上に


def test_stl_build(tmp_path):
    out = tmp_path / "a.stl"
    geometry.build(airfoil="naca0012", chord=1.0, mode="2d", out=str(out))
    assert out.exists() and out.stat().st_size > 0

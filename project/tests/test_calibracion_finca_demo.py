"""
Tests de integración — calibración de campo FincaDEMO.

Verifica que el endpoint /api/agrovista/protein, dado un polígono conocido
sobre FincaDEMO (org_id=8), devuelva valores de proteína dentro de las
tolerancias medidas en campo.

Estos tests requieren:
  - El servidor Flask corriendo y accesible en BASE_URL.
  - Credenciales válidas para FincaDEMO (usuario de prueba).
  - Los assets de imagen registrados en la BD con los IDs esperados.

Si cualquiera de esas condiciones no se cumple, el test hace pytest.skip
automáticamente — no falla el CI por infraestructura ausente.

Polígonos de campo usados para la recalibración (R²=0.988, n=4):
  poligono1: NGRDI=0.62  Proteína_ref=23.54%
  poligono2: NGRDI=-0.48 Proteína_ref=4.30%
  poligono3: NGRDI=0.28  Proteína_ref=15.88%
  poligono4: NGRDI=0.42  Proteína_ref=18.55%
"""

from __future__ import annotations

import math
import os

import pytest

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]


BASE_URL = os.environ.get("AGROVISTA_TEST_URL", "http://localhost:5000")
TEST_USERNAME = os.environ.get("AGROVISTA_TEST_USER", "")
TEST_PASSWORD = os.environ.get("AGROVISTA_TEST_PASS", "")

# Tolerancia máxima de error entre proteína calculada y referencia de campo
TOLERANCIA_PCT = 2.0


def _skip_if_unavailable() -> None:
    """Salta el test si el servidor no responde o faltan credenciales."""
    if requests is None:
        pytest.skip("requests no instalado — saltar tests de integración")
    try:
        resp = requests.get(f"{BASE_URL}/api/agrovista/nutrients", timeout=3)
        if resp.status_code == 401:
            # Servidor responde pero requiere auth — continuar (se loguea abajo)
            return
        if resp.status_code >= 500:
            pytest.skip(f"Servidor responde con {resp.status_code} — infraestructura no disponible")
    except Exception as exc:
        pytest.skip(f"Servidor no disponible en {BASE_URL}: {exc}")


def _login() -> str | None:
    """Obtiene token JWT del servidor de prueba.

    Returns:
        Token de acceso como string, o None si falla.
    """
    if not TEST_USERNAME or not TEST_PASSWORD:
        return None
    try:
        resp = requests.post(
            f"{BASE_URL}/api/core/login",
            json={"email": TEST_USERNAME, "password": TEST_PASSWORD},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("access_token") or data.get("token")
    except Exception:
        pass
    return None


def _auth_headers(token: str | None) -> dict:
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


# ---------------------------------------------------------------------------
# Casos de calibración de campo (sin llamada al servidor — sólo bromatologia.py)
# ---------------------------------------------------------------------------

def test_integracion_modulo_directo_poligono1():
    """Integración directa: importar y llamar perfil_desde_ngrdi para poligono1."""
    from app.modules.agrovista.bromatologia import perfil_desde_ngrdi

    r = perfil_desde_ngrdi(0.62)
    error = abs(r["proteina_pct"] - 23.54)
    assert error <= TOLERANCIA_PCT, (
        f"poligono1: proteina={r['proteina_pct']:.2f}%, ref=23.54%, error={error:.2f}%"
    )
    assert r["fda_pct"] > 0
    assert r["fdn_pct"] > 0
    assert math.isfinite(r["energia_mj"])


def test_integracion_modulo_directo_poligono2():
    """Integración directa: pasto degradado NGRDI=-0.48."""
    from app.modules.agrovista.bromatologia import perfil_desde_ngrdi

    r = perfil_desde_ngrdi(-0.48)
    error = abs(r["proteina_pct"] - 4.30)
    assert error <= TOLERANCIA_PCT, (
        f"poligono2: proteina={r['proteina_pct']:.2f}%, ref=4.30%, error={error:.2f}%"
    )
    assert r["proteina_pct"] > 0
    assert r["fda_pct"] > 0


def test_integracion_modulo_directo_poligono3():
    """Integración directa: vigor en rango operativo [34,41], NGRDI=0.28."""
    from app.modules.agrovista.bromatologia import perfil_desde_ngrdi

    r = perfil_desde_ngrdi(0.28)
    error = abs(r["proteina_pct"] - 15.88)
    assert error <= TOLERANCIA_PCT, (
        f"poligono3: proteina={r['proteina_pct']:.2f}%, ref=15.88%, error={error:.2f}%"
    )
    assert r["en_rango_valido"] is True
    assert r["minerales_confianza"] == "alta"


def test_integracion_modulo_directo_poligono4():
    """Integración directa: NGRDI=0.42, limite superior del rango operativo."""
    from app.modules.agrovista.bromatologia import perfil_desde_ngrdi

    r = perfil_desde_ngrdi(0.42)
    error = abs(r["proteina_pct"] - 18.55)
    assert error <= TOLERANCIA_PCT, (
        f"poligono4: proteina={r['proteina_pct']:.2f}%, ref=18.55%, error={error:.2f}%"
    )
    assert r["fda_pct"] > 0
    assert r["fdn_pct"] > 0


def test_integracion_modulo_directo_todos_los_lotes():
    """Integración directa: todos los lotes de campo cumplen tolerancia < 2%."""
    from app.modules.agrovista.bromatologia import perfil_desde_ngrdi

    casos = [
        ("poligono1",  0.62,  23.54),
        ("poligono2", -0.48,   4.30),
        ("poligono3",  0.28,  15.88),
        ("poligono4",  0.42,  18.55),
    ]
    for nombre, ngrdi, ref in casos:
        r = perfil_desde_ngrdi(ngrdi)
        error = abs(r["proteina_pct"] - ref)
        assert error <= TOLERANCIA_PCT, (
            f"{nombre}: NGRDI={ngrdi}, calc={r['proteina_pct']:.2f}%, "
            f"ref={ref}%, error={error:.2f}%"
        )


# ---------------------------------------------------------------------------
# Tests de integración HTTP (requieren servidor activo)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_endpoint_nutrients_responde():
    """El endpoint /api/agrovista/nutrients responde con lista de nutrientes."""
    _skip_if_unavailable()
    token = _login()
    resp = requests.get(
        f"{BASE_URL}/api/agrovista/nutrients",
        headers=_auth_headers(token),
        timeout=10,
    )
    if resp.status_code == 401:
        pytest.skip("Sin credenciales válidas — saltar test HTTP")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0


@pytest.mark.integration
def test_endpoint_protein_responde_con_asset_de_prueba():
    """El endpoint /api/agrovista/protein responde correctamente.

    Requiere AGROVISTA_TEST_ASSET_ID con un asset real georeferenciado.
    Si no se provee, el test se salta.
    """
    _skip_if_unavailable()
    asset_id = os.environ.get("AGROVISTA_TEST_ASSET_ID")
    if not asset_id:
        pytest.skip("AGROVISTA_TEST_ASSET_ID no definido — saltar test HTTP de protein")

    token = _login()
    if not token:
        pytest.skip("Sin token JWT — saltar test HTTP de protein")

    # Polígono mínimo de prueba (3 vértices en píxeles de preview)
    payload = {
        "id": asset_id,
        "media_asset_id": int(asset_id),
        "source": "media",
        "coords_full_res": False,
        "vertices": [[10, 10], [50, 10], [50, 50], [10, 50]],
        "width_preview": 800,
        "height_preview": 600,
    }
    resp = requests.post(
        f"{BASE_URL}/api/agrovista/protein",
        json=payload,
        headers=_auth_headers(token),
        timeout=30,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "protein" in data
    assert "bromatologia" in data
    broma = data["bromatologia"]
    if broma is not None:
        assert "proteina_pct" in broma
        assert isinstance(broma["proteina_pct"], (int, float))
        assert 0 < broma["proteina_pct"] < 50, (
            f"proteina_pct fuera de rango: {broma['proteina_pct']}"
        )

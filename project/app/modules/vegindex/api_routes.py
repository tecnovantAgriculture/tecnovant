"""Endpoints JSON para el cálculo de índices de vegetación."""

from __future__ import annotations

from flask import jsonify, request

from . import vegindex_api as api
from .controller import compute_from_source


@api.route("/ping", methods=["GET"])
def ping():
    """Responder con un mensaje de latido para probar la API de vegindex."""

    return jsonify(message="pong from vegindex API")


@api.route("/compute", methods=["POST"])
def compute():
    """Calcular estadísticas de índices vegetativos a partir de una fuente.

    El cuerpo de la petición debe ser JSON e incluir la clave ``source`` con
    una URI comprensible para la capa de almacenamiento, por ejemplo
    ``local:/ruta/a/archivo.tif`` o ``s3://bucket/key``. De forma opcional se
    puede añadir ``bbox`` con los límites en píxeles ``[xmin, ymin, xmax, ymax]``
    (coordenadas enteras) para recortar el cálculo a un subconjunto.

    La respuesta devuelve estadísticas resumidas (conteo, mínimos, máximos y
    media de VARI) junto con la media de proteína estimada, o un error HTTP 400
    cuando faltan parámetros o se produce una excepción durante el proceso.
    """

    payload = request.get_json(silent=True) or {}
    source = payload.get("source")
    bbox = payload.get("bbox")
    if not source:
        return (
            jsonify(
                error="source is required (e.g., local:/path.tif or s3://bucket/key)"
            ),
            400,
        )
    try:
        result = compute_from_source(source=source, bbox=bbox)
        return jsonify(result)
    except Exception as exc:
        return jsonify(error=str(exc)), 400

"""Rutas HTML para la carga y análisis de índices de vegetación."""

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for

from . import vegindex as web
from .controller import compute_from_source


@web.route("/hello")
def hello():
    """Mostrar el formulario de carga de fuentes para cálculo de VARI."""

    return render_template("vegindex/upload.j2")


@web.route("/analyze", methods=["POST"])
def analyze():
    """Procesar el formulario de análisis y renderizar el resultado o errores.

    La vista convierte el texto ingresado como ``source`` en una URI consumible
    por el controlador y, opcionalmente, interpreta ``bbox`` como una lista de
    cuatro enteros separados por comas. Ante errores de validación se comunica al
    usuario mediante ``flash`` y se redirige al formulario inicial.

    Cuando los parámetros son válidos se delega el cálculo a
    ``compute_from_source``. Cualquier excepción propagada también se transforma
    en un mensaje visible para el usuario final.
    """

    source = request.form.get("source", "").strip()
    bbox_text = request.form.get("bbox", "").strip()
    bbox = None
    if bbox_text:
        try:
            parts = [int(x) for x in bbox_text.split(",")]
            if len(parts) != 4:
                raise ValueError
            bbox = parts
        except Exception:
            flash("BBox must be four integers: xmin,ymin,xmax,ymax", "error")
            return redirect(url_for("vegindex.hello"))

    if not source:
        flash(
            "Source is required. Example: local:/data/image.tif or s3://bucket/key",
            "error",
        )
        return redirect(url_for("vegindex.hello"))

    try:
        result = compute_from_source(source=source, bbox=bbox)
        return render_template(
            "vegindex/result.j2", result=result, source=source, bbox=bbox
        )
    except Exception as e:
        flash(str(e), "error")
        return redirect(url_for("vegindex.hello"))

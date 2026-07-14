"""Server-side PDF export for foliage recommendation reports.

This exporter builds a text-first agronomic report from the selected
Recommendation payload. It does not capture browser screens and it does
not hard-code farm, lot, crop, date or nutrient values from sample files.
"""

from __future__ import annotations

import io
import re
import textwrap
import unicodedata
from datetime import datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 8,
    "font.weight": "regular",
    "axes.titlesize": 10,
    "axes.labelsize": 8,
    "pdf.fonttype": 42,
})
from app.modules.foliage_report.services.docx_export import (
    _load_cv_data,
    _load_mineral_balance,
    _load_report_payload,
)

FALLBACK_NOT_SUPPLIED = "Información no suministrada"
FALLBACK_NOT_APPLICABLE = "No aplica"
FALLBACK_NOT_DETERMINED = "No determinado"
FALLBACK_UNAVAILABLE = "Resultado no disponible"
FALLBACK_NOT_CLASSIFIABLE = "No clasificable con la información actual"

BRAND = "#0f766e"
DARK = "#111827"
MUTED = "#64748b"
BORDER = "#d8e3dd"
SOFT = "#f6faf8"
RED = "#dc2626"
AMBER = "#b45309"
GREEN = "#15803d"
BLUE = "#2563eb"

MACRO_SYMBOLS = {"N", "P", "K", "Ca", "Mg", "S"}
NUTRIENT_SYMBOLS = {
    "nitrogeno": "N",
    "fosforo": "P",
    "potasio": "K",
    "calcio": "Ca",
    "magnesio": "Mg",
    "azufre": "S",
    "hierro": "Fe",
    "manganeso": "Mn",
    "zinc": "Zn",
    "cobre": "Cu",
    "boro": "B",
    "molibdeno": "Mo",
    "silicio": "Si",
}

STATUS_TEXT = {
    "Deficiente": "Se encuentra por debajo del rango de suficiencia y puede limitar la respuesta productiva.",
    "Bajo": "Está ligeramente por debajo del objetivo; requiere seguimiento y validación en campo.",
    "Adecuado": "Se encuentra dentro del rango operativo esperado para la referencia usada.",
    "Alto": "Supera el objetivo; no se recomienda corrección directa sin revisar antagonismos.",
    "Excesivo": "Presenta exceso relativo; revisar posibles antagonismos, dilución o error de unidades.",
    FALLBACK_NOT_CLASSIFIABLE: "No se puede clasificar porque falta valor actual, ideal o unidad comparable.",
}


def build_report_pdf_bytes(report_id: int) -> io.BytesIO:
    """Build a professional agronomic PDF for a selected report."""
    payload = _load_report_payload(report_id)
    cv_data = _load_cv_data(payload)
    mineral_balance = _load_mineral_balance(payload)
    normalized = _normalize_payload(payload, cv_data, mineral_balance)

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        _cover_page(pdf, normalized)
        _technical_sheet_page(pdf, normalized)
        _nutritional_diagnosis_page(pdf, normalized)
        _interpretation_page(pdf, normalized)
        _balance_page(pdf, normalized)
        _recommendations_page(pdf, normalized)
        _traceability_page(pdf, normalized)
    buf.seek(0)
    return buf


def safe_report_filename(payload: dict[str, Any], extension: str = "pdf") -> str:
    """Return informe_agronomico_[finca]_[lote]_[fecha].ext."""
    common = ((payload.get("analysisData") or {}).get("common") or {})
    finca = _slug(common.get("finca") or "finca")
    lote = _slug(common.get("lote") or "lote")
    fecha = _slug(str(common.get("fechaAnalisis") or datetime.now().date()))
    return f"informe_agronomico_{finca}_{lote}_{fecha}.{extension.lstrip('.')}"


def _normalize_payload(payload: dict[str, Any], cv_data: dict, mineral_balance: dict) -> dict:
    analysis = payload.get("analysisData") or {}
    common = analysis.get("common") or {}
    lot = payload.get("lot") or {}
    crop = payload.get("crop") or {}
    objective = payload.get("productiveObjective") or {}
    mla = payload.get("minimum_law_analyses") or payload.get("minimumLawAnalyses") or {}
    foliar = analysis.get("foliar") or {}
    soil = analysis.get("soil") or {}
    nutrients = _build_nutrients(foliar, cv_data)
    limiting = _limiting_from_nutrients(nutrients, mla)
    data_quality = _validate_report_data(common, lot, crop, nutrients, objective)
    return {
        "id": payload.get("id"),
        "title": payload.get("title") or "Informe agronómico",
        "author": payload.get("author") or "Sistema",
        "organization": (payload.get("organization") or {}).get("name"),
        "common": common,
        "lot": lot,
        "crop": crop,
        "objective": objective,
        "foliar": foliar,
        "soil": soil,
        "nutrients": nutrients,
        "macro": [n for n in nutrients if n["group"] == "macro"],
        "micro": [n for n in nutrients if n["group"] == "micro"],
        "limiting": limiting,
        "mineral_balance": mineral_balance or {},
        "historical": payload.get("historicalData") or [],
        "trends": payload.get("trends") or {},
        "data_quality": data_quality,
        "comparison_label": (mla or {}).get("comparison_label") or FALLBACK_NOT_DETERMINED,
        "generated_at": datetime.now(),
    }


def _build_nutrients(foliar: dict, cv_data: dict) -> list[dict[str, Any]]:
    rows = []
    for key, entry in foliar.items():
        if key == "id" or not isinstance(entry, dict):
            continue
        symbol = NUTRIENT_SYMBOLS.get(_normalize_key(key), key[:2].title())
        actual = _to_float(entry.get("valor"))
        ideal = _to_float(entry.get("ideal"))
        pct = (actual / ideal * 100.0) if actual is not None and ideal and ideal > 0 else None
        status = _classify_pct(pct)
        gap = (actual - ideal) if actual is not None and ideal is not None else None
        rows.append(
            {
                "key": key,
                "name": key.replace("_", " ").capitalize(),
                "symbol": symbol,
                "actual": actual,
                "ideal": ideal,
                "gap": gap,
                "unit": entry.get("unidad") or FALLBACK_NOT_DETERMINED,
                "pct": pct,
                "cv": _to_float(cv_data.get(_normalize_key(key))),
                "status": status,
                "interpretation": STATUS_TEXT.get(status, FALLBACK_NOT_CLASSIFIABLE),
                "group": "macro" if symbol in MACRO_SYMBOLS else "micro",
            }
        )
    return sorted(rows, key=lambda r: (0 if r["group"] == "macro" else 1, r["symbol"]))


def _validate_report_data(common: dict, lot: dict, crop: dict, nutrients: list, objective: dict) -> list[str]:
    checks = []
    if not common.get("finca"):
        checks.append("Finca: " + FALLBACK_NOT_SUPPLIED)
    if not common.get("lote"):
        checks.append("Lote: " + FALLBACK_NOT_SUPPLIED)
    if not common.get("fechaAnalisis"):
        checks.append("Fecha de análisis: " + FALLBACK_NOT_SUPPLIED)
    if not crop.get("name"):
        checks.append("Cultivo: " + FALLBACK_NOT_SUPPLIED)
    if not lot.get("area"):
        checks.append("Área: " + FALLBACK_NOT_SUPPLIED)
    if not nutrients:
        checks.append("Análisis foliar: " + FALLBACK_UNAVAILABLE)
    if not any(n.get("ideal") for n in nutrients):
        checks.append("Rangos nutricionales: " + FALLBACK_NOT_CLASSIFIABLE)
    if not objective.get("target"):
        checks.append("Objetivo productivo: " + FALLBACK_NOT_SUPPLIED)
    return checks


def _limiting_from_nutrients(nutrients: list[dict[str, Any]], mla: dict) -> dict[str, Any]:
    explicit = (mla or {}).get("nutriente_limitante")
    classified = [n for n in nutrients if n["pct"] is not None]
    limiting = min(classified, key=lambda n: n["pct"], default=None)
    if explicit:
        for n in classified:
            if n["name"].lower() == str(explicit).lower() or n["key"].lower() == str(explicit).lower():
                limiting = n
                break
    if not limiting:
        return {"name": FALLBACK_NOT_DETERMINED, "pct": None, "status": FALLBACK_NOT_CLASSIFIABLE}
    return {"name": limiting["name"], "pct": limiting["pct"], "status": limiting["status"]}


def _cover_page(pdf: PdfPages, data: dict) -> None:
    fig, ax = _new_page()
    common = data["common"]
    crop = data["crop"]
    lot = data["lot"]

    ax.add_patch(plt.Rectangle((0, 0.965), 1, 0.012, transform=ax.transAxes, color=BRAND))
    ax.text(0.07, 0.91, "TECNOVAN", transform=ax.transAxes, color=BRAND, fontsize=14.5, fontweight="semibold")
    ax.text(0.07, 0.882, "Tecnología para el campo", transform=ax.transAxes, color=MUTED, fontsize=8.5)
    ax.text(0.93, 0.91, f"Informe N° {data['id'] or FALLBACK_NOT_DETERMINED}", transform=ax.transAxes, color=MUTED, fontsize=8.5, ha="right")
    ax.plot([0.07, 0.93], [0.855, 0.855], transform=ax.transAxes, color=BORDER, linewidth=1)

    ax.text(0.07, 0.795, "Informe agronómico", transform=ax.transAxes, color=DARK, fontsize=21, fontweight="semibold")
    ax.text(0.07, 0.755, "Análisis nutricional, diagnóstico y recomendaciones técnicas", transform=ax.transAxes, color=BRAND, fontsize=11)
    ax.text(0.07, 0.715, _value(data["title"]), transform=ax.transAxes, color=MUTED, fontsize=8.5)

    rows = [
        ("Finca", common.get("finca")),
        ("Lote", common.get("lote")),
        ("Cultivo", crop.get("name")),
        ("Área", _fmt_unit(lot.get("area"), "ha")),
        ("Fecha de muestreo/análisis", common.get("fechaAnalisis")),
        ("Referencia agronómica", data.get("comparison_label")),
        ("Responsable", data.get("author")),
        ("Generado", data["generated_at"].strftime("%Y-%m-%d %H:%M")),
    ]
    _kv_table(ax, rows, x=0.07, y=0.655, row_h=0.043)

    _section(ax, "Conclusión ejecutiva", 0.265)
    y = _paragraph(ax, _diagnostic_text(data), 0.07, 0.230, width=104, size=8.8, color=DARK)
    _paragraph(
        ax,
        "Este informe presenta datos registrados, cálculos derivados e interpretación técnica. Cuando un dato no existe, se declara explícitamente; no se reemplaza con información de otra finca, lote o fecha.",
        0.07,
        y - 0.025,
        width=106,
        size=7.8,
        color=MUTED,
    )
    _footer(ax, data, page=1)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

def _technical_sheet_page(pdf: PdfPages, data: dict) -> None:
    fig, ax = _new_page()
    _page_header(ax, "1. Ficha técnica y validación de datos", data)
    common = data["common"]
    obj = data["objective"]
    current = obj.get("current") or {}
    target = obj.get("target") or {}
    sheet = [
        ("Aforo actual", _fmt_unit(current.get("yield"), "t/ha")),
        ("Aforo objetivo", _fmt_unit(target.get("yield"), "t/ha")),
        ("Proteína actual", _fmt_unit(current.get("protein"), "%")),
        ("Proteína objetivo", _fmt_unit(target.get("protein"), "%")),
        ("Días de descanso", _value(common.get("diasDescanso"))),
        ("Mes", _value(common.get("mes"))),
        ("Análisis foliar", f"{len(data['nutrients'])} nutrientes evaluados" if data["nutrients"] else FALLBACK_UNAVAILABLE),
        ("Análisis de suelo", "Disponible" if data.get("soil") else FALLBACK_UNAVAILABLE),
    ]
    _kv_table(ax, sheet, x=0.07, y=0.80, row_h=0.045)

    _section(ax, "Validaciones aplicadas", 0.43)
    if data["data_quality"]:
        y = 0.39
        for item in data["data_quality"][:9]:
            _paragraph(ax, f"• {item}", 0.08, y, width=110, size=8.5, color=AMBER)
            y -= 0.035
    else:
        _paragraph(ax, "• Los campos mínimos del registro seleccionado están presentes.", 0.08, 0.39, width=110, size=8.5, color=GREEN)
        _paragraph(ax, "• La información se toma del informe seleccionado, sus análisis asociados y los objetivos nutricionales disponibles.", 0.08, 0.355, width=110, size=8.5, color=GREEN)

    _section(ax, "Fórmulas usadas", 0.300)
    formulas = [
        "% ideal = (valor actual / valor ideal) x 100, cuando ambos valores son comparables y el ideal es mayor que cero.",
        "Brecha = valor actual - valor ideal. Una brecha negativa indica déficit relativo; una positiva indica exceso relativo.",
        "Clasificación nutricional: deficiente < 80%, bajo 80-94.9%, adecuado 95-110%, alto 110.1-140%, excesivo > 140%.",
        "Balance mineral: convierte resultados foliares a requerimientos por hectárea usando el aforo disponible.",
    ]
    y = 0.265
    for formula in formulas:
        if y < 0.105:
            break
        y = _paragraph(ax, f"• {formula}", 0.08, y, width=96, size=7.1, color=DARK) - 0.018
    _footer(ax, data, page=2)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _nutritional_diagnosis_page(pdf: PdfPages, data: dict) -> None:
    fig, ax = _new_page()
    _page_header(ax, "2. Diagnóstico nutricional foliar", data)
    if not data["nutrients"]:
        _paragraph(ax, FALLBACK_UNAVAILABLE, 0.07, 0.76, width=110, size=10, color=MUTED)
    else:
        rows = []
        for n in data["nutrients"]:
            rows.append([
                n["symbol"],
                n["name"],
                _fmt_number(n["actual"]),
                n["unit"],
                _fmt_number(n["ideal"]),
                _fmt_pct(n["pct"]),
                _fmt_number(n["gap"]),
                n["status"],
            ])
        _draw_table(
            ax,
            ["Símb.", "Nutriente", "Actual", "Unidad", "Ideal", "% ideal", "Brecha", "Estado"],
            rows,
            x=0.055,
            y=0.79,
            w=0.89,
            row_h=0.034,
            font_size=5.6,
        )

    _section(ax, "Lectura técnica", 0.18)
    _paragraph(ax, _diagnostic_text(data), 0.07, 0.145, width=112, size=8.8, color=DARK)
    _footer(ax, data, page=3)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _interpretation_page(pdf: PdfPages, data: dict) -> None:
    fig, ax = _new_page()
    _page_header(ax, "3. Interpretación por nutriente", data)
    nutrients = data["nutrients"]
    if not nutrients:
        _paragraph(ax, FALLBACK_UNAVAILABLE, 0.07, 0.76, width=110, size=10, color=MUTED)
    else:
        y = 0.80
        for n in nutrients[:14]:
            color = _status_color(n["status"])
            ax.text(0.07, y, f"{n['symbol']} · {n['name']} — {n['status']}", transform=ax.transAxes, color=color, fontsize=9.2, fontweight="bold")
            detail = (
                f"Actual: {_fmt_number(n['actual'])} {n['unit']}; ideal: {_fmt_number(n['ideal'])} {n['unit']}; "
                f"suficiencia: {_fmt_pct(n['pct'])}; brecha: {_fmt_number(n['gap'])} {n['unit']}. "
                f"{n['interpretation']}"
            )
            lines = textwrap.wrap(detail, width=118)
            for idx, line in enumerate(lines[:2]):
                ax.text(0.09, y - 0.023 - idx * 0.021, line, transform=ax.transAxes, color=DARK, fontsize=7.5)
            y -= 0.066
            if y < 0.10:
                break
    _footer(ax, data, page=4)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _balance_page(pdf: PdfPages, data: dict) -> None:
    fig, ax = _new_page()
    _page_header(ax, "4. Balance mineral y metodología", data)
    mb = data["mineral_balance"] or {}
    entries = mb.get("entries") or []
    _section(ax, "Metodología", 0.80)
    _paragraph(ax, _method_note(mb), 0.07, 0.765, width=112, size=8.8, color=DARK)

    if entries:
        rows = []
        for e in entries[:12]:
            rows.append([
                e.get("name"),
                _fmt_number(e.get("actual_raw")),
                _fmt_number(e.get("objective_raw")),
                _fmt_number(e.get("actual_kg")),
                _fmt_number(e.get("objective_kg")),
                _fmt_number(e.get("difference_kg")),
                _fmt_number(e.get("nano_kg")),
            ])
        _draw_table(
            ax,
            ["Nut.", "Actual", "Obj.", "Act. kg/ha", "Obj. kg/ha", "Dif. kg/ha", "Nano kg/ha"],
            rows,
            x=0.055,
            y=0.63,
            w=0.89,
            row_h=0.034,
            font_size=6.0,
        )
        _paragraph(
            ax,
            f"Requerimiento total estimado: {_fmt_unit(mb.get('total_kg_ha'), 'kg/ha')}. Validar con producto disponible, estado fenológico, clima y criterio agronómico.",
            0.07,
            0.18,
            width=112,
            size=8.2,
            color=MUTED,
        )
    else:
        _paragraph(ax, FALLBACK_NOT_CLASSIFIABLE, 0.07, 0.60, width=110, size=9.5, color=AMBER)
    _footer(ax, data, page=5)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _recommendations_page(pdf: PdfPages, data: dict) -> None:
    fig, ax = _new_page()
    _page_header(ax, "5. Recomendaciones técnicas", data)
    nutrients = [n for n in data["nutrients"] if n["pct"] is not None]
    critical = [n for n in nutrients if n["status"] in {"Deficiente", "Bajo"}]
    excessive = [n for n in nutrients if n["status"] in {"Alto", "Excesivo"}]
    mb_entries = (data["mineral_balance"] or {}).get("entries") or []
    has_core = bool(nutrients) and any(n.get("ideal") for n in nutrients)

    _section(ax, "Criterio de emisión", 0.80)
    if not has_core:
        _paragraph(
            ax,
            "No se emiten recomendaciones automáticas porque faltan resultados comparables contra rangos u objetivos nutricionales. Se requiere completar el análisis antes de definir tratamientos.",
            0.07,
            0.765,
            width=112,
            size=9,
            color=AMBER,
        )
    else:
        bullets = []
        if critical:
            names = ", ".join(f"{n['symbol']} ({_fmt_pct(n['pct'])})" for n in critical[:6])
            bullets.append(f"Priorizar verificación y corrección de nutrientes por debajo del objetivo: {names}.")
        if excessive:
            names = ", ".join(f"{n['symbol']} ({_fmt_pct(n['pct'])})" for n in excessive[:6])
            bullets.append(f"Evitar aplicaciones que incrementen nutrientes en exceso relativo: {names}.")
        if mb_entries:
            bullets.append("Usar la tabla de balance mineral como base de dosificación; revisar compatibilidad de productos, estado fenológico y condiciones de aplicación.")
        bullets.append("Validar el diagnóstico con observación de campo, historial de manejo y consistencia de unidades del laboratorio.")
        y = 0.755
        for bullet in bullets:
            _paragraph(ax, f"• {bullet}", 0.08, y, width=110, size=8.6, color=DARK)
            y -= 0.065

    _section(ax, "Limitaciones", 0.35)
    limitations = data["data_quality"] or ["No se detectaron faltantes críticos en los datos usados para el informe."]
    y = 0.315
    for item in limitations[:6]:
        _paragraph(ax, f"• {item}", 0.08, y, width=110, size=8.2, color=MUTED)
        y -= 0.042
    _footer(ax, data, page=6)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _traceability_page(pdf: PdfPages, data: dict) -> None:
    fig, ax = _new_page()
    _page_header(ax, "6. Histórico y trazabilidad", data)
    historical = data["historical"]
    if len(historical) < 2:
        _paragraph(ax, "No hay suficiente información histórica para calcular tendencias confiables.", 0.07, 0.78, width=112, size=9.5, color=MUTED)
    else:
        keys = []
        for row in historical:
            for key in row:
                if key != "fecha" and key not in keys:
                    keys.append(key)
        rows = [[str(r.get("fecha", ""))] + [_fmt_number(r.get(k)) for k in keys[:7]] for r in historical[:10]]
        _draw_table(ax, ["Fecha"] + [k.capitalize() for k in keys[:7]], rows, x=0.055, y=0.78, w=0.89, row_h=0.034, font_size=6.2)

        _section(ax, "Lectura histórica", 0.34)
        trends = data.get("trends") or {}
        if trends:
            y = 0.305
            for nutrient, trend in list(trends.items())[:7]:
                pct = _to_float(trend.get("percentage_change"))
                if pct is None:
                    continue
                direction = "incrementó" if pct >= 0 else "disminuyó"
                _paragraph(
                    ax,
                    f"• {nutrient.capitalize()} {direction} {abs(pct):.1f}% entre el primer y último registro disponible.",
                    0.08,
                    y,
                    width=110,
                    size=8.2,
                    color=DARK,
                )
                y -= 0.04
        else:
            _paragraph(ax, "No se calcularon tendencias por falta de series comparables.", 0.08, 0.305, width=110, size=8.2, color=MUTED)
    _footer(ax, data, page=7)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def _diagnostic_text(data: dict) -> str:
    limiting = data["limiting"]
    nutrients = data["nutrients"]
    if not nutrients:
        return FALLBACK_UNAVAILABLE
    if limiting.get("pct") is None:
        return FALLBACK_NOT_CLASSIFIABLE
    critical = [n for n in nutrients if n["status"] in {"Deficiente", "Bajo"}]
    excessive = [n for n in nutrients if n["status"] in {"Alto", "Excesivo"}]
    parts = [
        f"El nutriente más restrictivo del análisis es {limiting['name']} con {_fmt_pct(limiting['pct'])} del valor ideal y clasificación {limiting['status']}.",
    ]
    if critical:
        parts.append(f"Se identifican {len(critical)} nutrientes por debajo del objetivo, por lo que el manejo debe priorizar corrección y seguimiento técnico.")
    else:
        parts.append("No se identifican nutrientes por debajo del objetivo con los datos comparables disponibles.")
    if excessive:
        parts.append(f"También hay {len(excessive)} nutrientes por encima del objetivo; se recomienda evitar aportes adicionales sin validar antagonismos y unidades.")
    return " ".join(parts)


def _method_note(mineral_balance: dict) -> str:
    if not mineral_balance.get("entries"):
        return FALLBACK_NOT_CLASSIFIABLE
    return (
        "El balance convierte concentraciones foliares a requerimientos por hectárea usando el aforo asociado al informe. "
        "Para macronutrientes se usa la concentración porcentual frente al aforo; para micronutrientes se usa ppm ajustado por aforo. "
        "La diferencia negativa representa déficit relativo; los excedentes se informan, pero no generan dosis correctiva automática."
    )


def _new_page():
    fig = plt.figure(figsize=(8.27, 11.69), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    return fig, ax


def _page_header(ax, title: str, data: dict) -> None:
    ax.text(0.07, 0.91, title, transform=ax.transAxes, color=DARK, fontsize=14.5, fontweight="semibold")
    common = data["common"]
    ax.text(
        0.07,
        0.878,
        f"{_value(common.get('finca'))} · {_value(common.get('lote'))} · {_value(common.get('fechaAnalisis'))}",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=8.5,
    )
    ax.plot([0.07, 0.93], [0.858, 0.858], transform=ax.transAxes, color=BORDER, linewidth=1)


def _footer(ax, data: dict, page: int) -> None:
    common = data["common"]
    ax.plot([0.07, 0.93], [0.055, 0.055], transform=ax.transAxes, color=BORDER, linewidth=0.8)
    ax.text(
        0.07,
        0.035,
        f"Informe agronómico · {_value(common.get('finca'))} · {_value(common.get('lote'))}",
        transform=ax.transAxes,
        color=MUTED,
        fontsize=7,
    )
    ax.text(0.93, 0.035, f"Página {page}", transform=ax.transAxes, color=MUTED, fontsize=5.8, ha="right")


def _section(ax, text: str, y: float) -> None:
    ax.text(0.07, y, text, transform=ax.transAxes, color=BRAND, fontsize=10.5, fontweight="semibold")
    ax.plot([0.07, 0.93], [y - 0.012, y - 0.012], transform=ax.transAxes, color=BORDER, linewidth=0.7)


def _paragraph(ax, text: str, x: float, y: float, *, width: int, size: float, color: str) -> float:
    lines = textwrap.wrap(str(text or FALLBACK_NOT_SUPPLIED), width=width) or [FALLBACK_NOT_SUPPLIED]
    for idx, line in enumerate(lines):
        ax.text(x, y - idx * (size / 370), line, transform=ax.transAxes, color=color, fontsize=size)
    return y - len(lines) * (size / 370)


def _kv_table(ax, rows: list[tuple[str, Any]], x: float, y: float, row_h: float) -> None:
    for idx, (label, value) in enumerate(rows):
        yy = y - idx * row_h
        ax.add_patch(plt.Rectangle((x, yy - row_h + 0.006), 0.86, row_h - 0.006, transform=ax.transAxes, facecolor=SOFT if idx % 2 == 0 else "white", edgecolor=BORDER, linewidth=0.6))
        ax.text(x + 0.014, yy - row_h / 2, str(label), transform=ax.transAxes, color=MUTED, fontsize=7.8, fontweight="bold", va="center")
        ax.text(x + 0.32, yy - row_h / 2, _value(value), transform=ax.transAxes, color=DARK, fontsize=8.2, va="center")


def _draw_table(ax, headers: list[str], rows: list[list[Any]], *, x: float, y: float, w: float, row_h: float, font_size: float) -> None:
    if not rows:
        ax.text(x, y, FALLBACK_UNAVAILABLE, transform=ax.transAxes, color=MUTED, fontsize=9)
        return
    h = min(row_h * (len(rows) + 1), y - 0.090)
    limits = _column_limits(len(headers))
    prepared = [[_table_value(c, limits[idx] if idx < len(limits) else 18) for idx, c in enumerate(row)] for row in rows]
    table = ax.table(
        cellText=prepared,
        colLabels=headers,
        cellLoc="left",
        colLoc="left",
        bbox=[x, y - h, w, h],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(font_size)
    for (r, _c), cell in table.get_celld().items():
        cell.set_edgecolor(BORDER)
        cell.PAD = 0.012
        txt = cell.get_text()
        txt.set_wrap(False)
        if r == 0:
            cell.set_facecolor(BRAND)
            txt.set_color("white")
            txt.set_fontweight("bold")
        elif r % 2 == 0:
            cell.set_facecolor("#f8fafc")


def _column_limits(count: int) -> list[int]:
    if count >= 8:
        return [7, 16, 10, 10, 10, 9, 9, 14]
    if count == 7:
        return [10, 9, 9, 10, 10, 10, 10]
    return [18] * count

def _table_value(value: Any, limit: int = 20) -> str:
    text = _value(value)
    replacements = {
        FALLBACK_NOT_DETERMINED: "N/D",
        FALLBACK_NOT_SUPPLIED: "Sin dato",
        FALLBACK_UNAVAILABLE: "No disponible",
        FALLBACK_NOT_CLASSIFIABLE: "No clasificable",
        "No clasificable con la información actual": "No clasificable",
        "No clasificable con la informaciÃ³n actual": "No clasificable",
    }
    text = replacements.get(text, text)
    return _shorten(text, limit)


def _shorten(text: str, limit: int) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"

def _classify_pct(pct: float | None) -> str:
    if pct is None:
        return FALLBACK_NOT_CLASSIFIABLE
    if pct < 80:
        return "Deficiente"
    if pct < 95:
        return "Bajo"
    if pct <= 110:
        return "Adecuado"
    if pct <= 140:
        return "Alto"
    return "Excesivo"


def _status_color(status: str) -> str:
    return {
        "Deficiente": RED,
        "Bajo": AMBER,
        "Adecuado": GREEN,
        "Alto": BLUE,
        "Excesivo": "#7c3aed",
    }.get(status, "#94a3b8")


def _fmt_pct(value: Any) -> str:
    number = _to_float(value)
    return FALLBACK_NOT_DETERMINED if number is None else f"{number:.1f}%"


def _fmt_unit(value: Any, unit: str) -> str:
    number = _to_float(value)
    return FALLBACK_NOT_DETERMINED if number is None else f"{number:.2f} {unit}"


def _fmt_number(value: Any) -> str:
    number = _to_float(value)
    return FALLBACK_NOT_DETERMINED if number is None else f"{number:.2f}"


def _value(value: Any) -> str:
    if value is None or value == "":
        return FALLBACK_NOT_SUPPLIED
    return str(value)


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_key(value: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", str(value).lower())
        if unicodedata.category(c) != "Mn"
    ).replace(" ", "")


def _slug(value: str) -> str:
    normalized = _normalize_key(value).replace("/", "_")
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", normalized).strip("_")
    return cleaned[:80] or "sin_dato"
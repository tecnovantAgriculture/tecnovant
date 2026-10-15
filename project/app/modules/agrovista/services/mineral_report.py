from __future__ import annotations

import io
import textwrap
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


GREEN = "#087F5B"
DARK = "#15221D"
BLUE = "#0877B9"
LIGHT = "#F1F5F3"
RED = "#D64545"
AMBER = "#D99000"
GRAY = "#64748B"


def _text(value, limit=500):
    return str(value or "").strip()[:limit]


def _number(value):
    try:
        result = float(value)
        return result if result == result else None
    except (TypeError, ValueError):
        return None


def _wrap(value, width=95):
    return "\n".join(textwrap.wrap(_text(value, 3000), width=width)) or "--"


def _footer(fig, page):
    fig.text(0.06, 0.025, "TECNOVANT | Tecnologia para el campo", fontsize=7, color=GRAY)
    fig.text(0.94, 0.025, f"Pagina {page}", fontsize=7, color=GRAY, ha="right")
    fig.text(0.5, 0.025, "Documento tecnico de apoyo a la decision agronomica", fontsize=7, color=GRAY, ha="center")


def _base_page(pdf, page, title=None):
    fig = plt.figure(figsize=(8.27, 11.69), facecolor="white")
    if title:
        fig.patches.extend([plt.Rectangle((0, .935), 1, .065, transform=fig.transFigure, color=GREEN, zorder=-1)])
        fig.text(.06, .962, title, color="white", fontsize=15, weight="bold", va="center")
    _footer(fig, page)
    return fig


def _status(percent):
    if percent is None:
        return "Sin referencia", GRAY
    if percent < 80:
        return "Bajo", RED
    if percent <= 120:
        return "Adecuado", GREEN
    return "Alto", AMBER


def _nutrients(payload):
    rows = []
    for raw in payload.get("nutrients") or []:
        actual, ideal = _number(raw.get("actual")), _number(raw.get("ideal"))
        percent = actual / ideal * 100 if actual is not None and ideal and ideal > 0 else None
        status, color = _status(percent)
        rows.append({
            "name": _text(raw.get("name"), 80),
            "symbol": _text(raw.get("symbol"), 8),
            "unit": _text(raw.get("unit"), 20),
            "actual": actual,
            "ideal": ideal,
            "percent": percent,
            "status": status,
            "color": color,
            "is_micro": bool(raw.get("is_micro")),
        })
    return rows


def _fmt(value, digits=3):
    if value is None:
        return "--"
    rendered = f"{value:.{digits}f}"
    return rendered.rstrip("0").rstrip(".").replace(".", ",")


def generate_mineral_report(payload, logo_path=None):
    nutrients = _nutrients(payload)
    meta = payload.get("meta") or {}
    professional = payload.get("professional") or {}
    notes = _text(payload.get("notes"), 3000)
    low = [row for row in nutrients if row["status"] == "Bajo"]
    adequate = [row for row in nutrients if row["status"] == "Adecuado"]
    high = [row for row in nutrients if row["status"] == "Alto"]
    referenced = [row for row in nutrients if row["percent"] is not None]
    limiting = min(referenced, key=lambda row: row["percent"], default=None)
    output = io.BytesIO()

    with PdfPages(output) as pdf:
        fig = _base_page(pdf, 1)
        fig.patches.extend([plt.Rectangle((0, .79), 1, .21, transform=fig.transFigure, color=GREEN, zorder=-1)])
        if logo_path and Path(logo_path).exists():
            try:
                logo = plt.imread(str(logo_path))
                axis = fig.add_axes([.06, .875, .17, .09])
                axis.imshow(logo); axis.axis("off")
            except Exception:
                pass
        fig.text(.06, .82, "INFORME TECNICO", fontsize=12, color="white", weight="bold")
        fig.text(.06, .765, "Balance mineral y analisis foliar", fontsize=24, color=DARK, weight="bold")
        fig.text(.06, .73, f"Informe No. {_text(meta.get('report_id'), 40) or datetime.now().strftime('%Y%m%d-%H%M')}", fontsize=9, color=GRAY)

        info = [
            ("Cliente", professional.get("client_name")),
            ("Finca", meta.get("farm")),
            ("Lote / Potrero", meta.get("lot")),
            ("Cultivo objetivo", meta.get("crop")),
            ("Fecha del analisis", meta.get("analysis_date")),
            ("Dias de descanso", meta.get("rest_days")),
            ("Ortofoto", meta.get("orthophoto")),
            ("Generado", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ]
        y = .67
        for index, (label, value) in enumerate(info):
            x = .06 if index % 2 == 0 else .53
            if index % 2 == 0 and index:
                y -= .067
            fig.text(x, y, label.upper(), fontsize=7, color=GRAY, weight="bold")
            fig.text(x, y-.025, _text(value, 90) or "--", fontsize=10, color=DARK)

        fig.text(.06, .37, "RESUMEN EJECUTIVO", fontsize=11, color=GREEN, weight="bold")
        summary = [
            ("BAJOS", len(low), RED),
            ("ADECUADOS", len(adequate), GREEN),
            ("ALTOS", len(high), AMBER),
            ("EVALUADOS", len(referenced), BLUE),
        ]
        for index, (label, value, color) in enumerate(summary):
            x = .06 + index * .225
            fig.patches.extend([plt.Rectangle((x, .275), .19, .07, transform=fig.transFigure, facecolor=LIGHT, edgecolor="#D8E2DD")])
            fig.text(x+.018, .318, label, fontsize=7, color=GRAY, weight="bold")
            fig.text(x+.018, .288, str(value), fontsize=17, color=color, weight="bold")

        if limiting:
            executive = (f"La comparacion con el objetivo seleccionado identifica a {limiting['name']} "
                         f"({limiting['symbol']}) como el nutriente con menor proporcion relativa "
                         f"({limiting['percent']:.1f}% del valor de referencia). ")
        else:
            executive = "No fue posible calcular proporciones frente a un objetivo nutricional. "
        executive += (f"Se clasificaron {len(low)} nutrientes en nivel bajo, {len(adequate)} en rango "
                      f"comparativo adecuado y {len(high)} en nivel alto. La interpretacion debe "
                      "integrarse con estado fenologico, muestreo, suelo, clima e historial de manejo.")
        fig.text(.06, .22, _wrap(executive, 105), fontsize=9, color=DARK, va="top", linespacing=1.55)
        fig.text(.06, .095, "ALCANCE DEL DOCUMENTO", fontsize=8, color=GREEN, weight="bold")
        fig.text(.06, .073, _wrap("Los resultados expresan una comparacion tecnica con el objetivo seleccionado. No constituyen por si solos una formula de fertilizacion ni reemplazan la inspeccion de campo y la validacion de un ingeniero agronomo.", 120), fontsize=7.5, color=GRAY, va="top")
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig = _base_page(pdf, 2, "Resultados del analisis foliar")
        axis = fig.add_axes([.055, .12, .89, .77]); axis.axis("off")
        headers = ["Nutriente", "Simbolo", "Actual", "Unidad", "Objetivo", "% objetivo", "Estado"]
        cells = []
        for row in nutrients:
            cells.append([row["name"], row["symbol"], _fmt(row["actual"]), row["unit"] or "--",
                          _fmt(row["ideal"]), "--" if row["percent"] is None else f"{row['percent']:.1f}%",
                          row["status"]])
        if not cells:
            cells = [["Sin datos", "--", "--", "--", "--", "--", "Sin referencia"]]
        table = axis.table(cellText=cells, colLabels=headers, cellLoc="center", colLoc="center",
                           loc="upper center", colWidths=[.20,.08,.11,.10,.11,.13,.14])
        table.auto_set_font_size(False); table.set_fontsize(7.6); table.scale(1, 1.65)
        for col in range(len(headers)):
            table[(0,col)].set_facecolor(GREEN); table[(0,col)].set_text_props(color="white", weight="bold")
        for row_index, row in enumerate(nutrients, start=1):
            if row_index % 2 == 0:
                for col in range(len(headers)): table[(row_index,col)].set_facecolor("#F8FAF9")
            table[(row_index,6)].set_text_props(color=row["color"], weight="bold")
        fig.text(.06, .085, "Criterio visual: bajo < 80% | adecuado 80-120% | alto > 120% del objetivo seleccionado.", fontsize=7.5, color=GRAY)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig = _base_page(pdf, 3, "Perfil nutricional comparativo")
        groups = [([row for row in nutrients if not row["is_micro"]], "Macronutrientes"),
                  ([row for row in nutrients if row["is_micro"]], "Micronutrientes")]
        for index, (rows, title) in enumerate(groups):
            axis = fig.add_axes([.11, .55-index*.42, .80, .30])
            axis.axvspan(80, 120, color="#D8F3E7", alpha=.8)
            axis.axvline(100, color=GREEN, linewidth=1, linestyle="--")
            if rows:
                values = [min(row["percent"] or 0, 160) for row in rows]
                colors = [row["color"] for row in rows]
                axis.barh([row["symbol"] for row in rows], values, color=colors, height=.55)
                for pos, (value, row) in enumerate(zip(values, rows)):
                    label = "--" if row["percent"] is None else f"{row['percent']:.0f}%"
                    axis.text(min(value+2, 162), pos, label, va="center", fontsize=7)
            axis.set_xlim(0, 170); axis.set_title(title, loc="left", color=DARK, weight="bold", fontsize=11)
            axis.set_xlabel("Porcentaje respecto al objetivo", fontsize=8, color=GRAY)
            axis.grid(axis="x", alpha=.18); axis.spines[["top","right","left"]].set_visible(False)
            axis.tick_params(labelsize=8)
        fig.text(.06, .09, _wrap("La franja verde representa el intervalo comparativo de 80% a 120%. Las barras no sustituyen rangos de suficiencia especificos por cultivo, tejido y etapa fenologica.", 125), fontsize=7.5, color=GRAY)
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

        fig = _base_page(pdf, 4, "Interpretacion y concepto agronomico")
        y = .88
        sections = []
        if low:
            sections.append(("NUTRIENTES POR DEBAJO DEL OBJETIVO", RED,
                             "Se observan niveles relativos bajos en " + ", ".join(f"{r['name']} ({r['symbol']})" for r in low) + ". Conviene verificar representatividad del muestreo, etapa fenologica, humedad, condicion radicular, pH y disponibilidad en suelo antes de establecer una correccion."))
        if high:
            sections.append(("NUTRIENTES POR ENCIMA DEL OBJETIVO", AMBER,
                             "Los valores relativos altos corresponden a " + ", ".join(f"{r['name']} ({r['symbol']})" for r in high) + ". Se recomienda revisar aplicaciones recientes, concentracion de la muestra y posibles antagonismos nutricionales."))
        if adequate:
            sections.append(("NUTRIENTES EN RANGO COMPARATIVO", GREEN,
                             "Presentan relacion entre 80% y 120% del objetivo: " + ", ".join(f"{r['name']} ({r['symbol']})" for r in adequate) + ". Deben mantenerse bajo seguimiento junto con rendimiento y evolucion temporal."))
        if limiting:
            sections.append(("FACTOR POTENCIALMENTE LIMITANTE", BLUE,
                             f"{limiting['name']} ({limiting['symbol']}) presenta la menor proporcion frente al objetivo ({limiting['percent']:.1f}%). Bajo el principio de Liebig puede actuar como limitante potencial, pero debe confirmarse con inspeccion de campo y analisis complementarios."))
        if not sections:
            sections.append(("INFORMACION INSUFICIENTE", GRAY, "No existen valores comparables suficientes para emitir una interpretacion relativa."))

        for title, color, body in sections:
            fig.text(.06, y, title, fontsize=9, color=color, weight="bold")
            wrapped = _wrap(body, 112)
            fig.text(.06, y-.027, wrapped, fontsize=8.2, color=DARK, va="top", linespacing=1.45)
            y -= .075 + .019 * wrapped.count("\n")
        fig.text(.06, max(y-.005,.29), "OBSERVACIONES DEL PROFESIONAL", fontsize=9, color=GREEN, weight="bold")
        fig.text(.06, max(y-.035,.26), _wrap(notes or "Sin observaciones adicionales.", 112), fontsize=8.2, color=DARK, va="top", linespacing=1.45)

        fig.patches.extend([plt.Rectangle((.06,.09),.88,.12,transform=fig.transFigure,facecolor=LIGHT,edgecolor="#D8E2DD")])
        fig.text(.08,.178,"RESPONSABLE DEL INFORME",fontsize=7,color=GRAY,weight="bold")
        fig.text(.08,.145,_text(professional.get("name"),100) or "Profesional responsable",fontsize=10,color=DARK,weight="bold")
        license_value = _text(professional.get("license"),80)
        fig.text(.08,.118,("Matricula profesional: "+license_value) if license_value else "Matricula profesional: No registrada",fontsize=8,color=GRAY)
        fig.add_artist(plt.Line2D([.60,.90],[.135,.135],transform=fig.transFigure,color="#94A3B8",linewidth=.8))
        fig.text(.75,.112,"Firma",fontsize=7,color=GRAY,ha="center")
        pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

    output.seek(0)
    return output

from __future__ import annotations

import io
import textwrap
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch, Rectangle


NAVY = "#17324D"
BLUE = "#0088CF"
BLUE_DARK = "#006AA3"
TEXT = "#243447"
MUTED = "#66788A"
BORDER = "#D9E2EA"
SURFACE = "#F6F8FA"
LOW = "#C94B4B"
OK = "#27865B"
HIGH = "#D18721"


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


def _fmt(value, digits=3):
    if value is None:
        return "--"
    rendered = f"{value:.{digits}f}"
    return rendered.rstrip("0").rstrip(".").replace(".", ",")


def _status(percent):
    if percent is None:
        return "Sin referencia", MUTED
    if percent < 80:
        return "Bajo", LOW
    if percent <= 120:
        return "Adecuado", OK
    return "Alto", HIGH


def _nutrients(payload):
    rows = []
    for raw in payload.get("nutrients") or []:
        actual = _number(raw.get("actual"))
        ideal = _number(raw.get("ideal"))
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


def _page(number, title=None, subtitle=None):
    fig = plt.figure(figsize=(8.27, 11.69), facecolor="white")
    fig.patches.append(Rectangle((0.055, 0.958), 0.89, 0.004, transform=fig.transFigure, color=BLUE))
    if title:
        fig.text(0.06, 0.925, title, fontsize=15, color=NAVY, weight="bold", va="top")
    if subtitle:
        fig.text(0.06, 0.895, subtitle, fontsize=8, color=MUTED, va="top")
    fig.text(0.06, 0.032, "TECNOVANT  |  Tecnología para el campo", fontsize=7, color=MUTED)
    fig.text(0.94, 0.032, f"Página {number}", fontsize=7, color=MUTED, ha="right")
    return fig


def _card(fig, x, y, width, height, face="white", edge=BORDER, radius=0.012):
    patch = FancyBboxPatch(
        (x, y), width, height,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        transform=fig.transFigure, facecolor=face, edgecolor=edge, linewidth=0.8,
    )
    fig.patches.append(patch)
    return patch


def _add_logo(fig, logo_path):
    if not logo_path or not Path(logo_path).exists():
        fig.text(0.06, 0.972, "TECNOVANT", fontsize=11, color=NAVY, weight="bold", va="bottom")
        return
    try:
        logo = plt.imread(str(logo_path))
        axis = fig.add_axes([0.06, 0.966, 0.16, 0.026])
        axis.imshow(logo)
        axis.axis("off")
    except Exception:
        fig.text(0.06, 0.972, "TECNOVANT", fontsize=11, color=NAVY, weight="bold", va="bottom")


def _save(pdf, fig):
    pdf.savefig(fig, facecolor="white")
    plt.close(fig)


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
    generated = datetime.now()
    output = io.BytesIO()

    with PdfPages(output) as pdf:
        # Página 1: identificación y resumen ejecutivo.
        fig = _page(1)
        _add_logo(fig, logo_path)
        fig.text(0.06, 0.91, "INFORME AGRONÓMICO", fontsize=9, color=BLUE_DARK, weight="bold")
        fig.text(0.06, 0.865, "Balance mineral y análisis foliar", fontsize=22, color=NAVY, weight="bold")
        fig.text(
            0.06, 0.837,
            f"Informe {_text(meta.get('report_id'), 40) or generated.strftime('%Y%m%d-%H%M')}  ·  {generated.strftime('%d/%m/%Y %H:%M')}",
            fontsize=8, color=MUTED,
        )

        _card(fig, 0.06, 0.625, 0.88, 0.17, face=SURFACE)
        info = [
            ("Finca", meta.get("farm")),
            ("Lote / potrero", meta.get("lot")),
            ("Cultivo objetivo", meta.get("crop")),
            ("Fecha de análisis", meta.get("analysis_date")),
            ("Días de descanso", meta.get("rest_days")),
            ("Ortofoto", meta.get("orthophoto")),
        ]
        for index, (label, value) in enumerate(info):
            col, row = index % 2, index // 2
            x = 0.085 + col * 0.43
            y = 0.755 - row * 0.05
            fig.text(x, y, label.upper(), fontsize=6.8, color=MUTED, weight="bold")
            fig.text(x, y - 0.021, _text(value, 75) or "--", fontsize=9, color=TEXT)

        fig.text(0.06, 0.575, "Resumen del diagnóstico", fontsize=11, color=NAVY, weight="bold")
        cards = [
            ("Bajos", len(low), LOW),
            ("Adecuados", len(adequate), OK),
            ("Altos", len(high), HIGH),
            ("Evaluados", len(referenced), BLUE_DARK),
        ]
        for index, (label, value, color) in enumerate(cards):
            x = 0.06 + index * 0.225
            _card(fig, x, 0.485, 0.195, 0.065, face="white")
            fig.text(x + 0.016, 0.528, label.upper(), fontsize=6.7, color=MUTED, weight="bold")
            fig.text(x + 0.016, 0.497, str(value), fontsize=17, color=color, weight="bold")

        if limiting:
            headline = f"Nutriente potencialmente limitante: {limiting['name']} ({limiting['symbol']})"
            detail = (
                f"Presenta {limiting['percent']:.1f}% del valor objetivo. "
                f"El análisis identifica {len(low)} nutrientes bajos, {len(adequate)} adecuados "
                f"y {len(high)} altos frente a la referencia seleccionada."
            )
        else:
            headline = "No fue posible determinar un nutriente limitante"
            detail = "No existen suficientes valores comparables frente al objetivo seleccionado."
        _card(fig, 0.06, 0.335, 0.88, 0.105, face="#F3F8FC", edge="#C9DFED")
        fig.text(0.085, 0.407, headline, fontsize=10, color=NAVY, weight="bold")
        fig.text(0.085, 0.378, _wrap(detail, 104), fontsize=8.5, color=TEXT, va="top", linespacing=1.45)

        fig.text(0.06, 0.275, "Lectura técnica", fontsize=11, color=NAVY, weight="bold")
        interpretation = (
            "Los resultados comparan la concentración foliar observada con el objetivo nutricional "
            "seleccionado. La lectura debe integrarse con etapa fenológica, uniformidad del muestreo, "
            "condición radicular, pH, humedad, clima, historial de fertilización y respuesta productiva."
        )
        fig.text(0.06, 0.242, _wrap(interpretation, 112), fontsize=8.7, color=TEXT, va="top", linespacing=1.55)

        _card(fig, 0.06, 0.095, 0.88, 0.075, face="#FFF9EE", edge="#ECD9AE")
        fig.text(0.083, 0.142, "ALCANCE", fontsize=7, color=HIGH, weight="bold")
        fig.text(
            0.083, 0.119,
            _wrap("Este documento es una herramienta de apoyo. No constituye por sí solo una fórmula de fertilización ni reemplaza la validación de campo por un profesional.", 120),
            fontsize=7.5, color=TEXT, va="top",
        )
        _save(pdf, fig)

        # Página 2: tabla clara, sin barras decorativas.
        fig = _page(2, "Resultados del análisis foliar", "Comparación frente al objetivo nutricional seleccionado")
        axis = fig.add_axes([0.06, 0.16, 0.88, 0.69])
        axis.axis("off")
        headers = ["Nutriente", "Símbolo", "Actual", "Unidad", "Objetivo", "% objetivo", "Estado"]
        cells = [
            [
                row["name"], row["symbol"], _fmt(row["actual"]), row["unit"] or "--",
                _fmt(row["ideal"]), "--" if row["percent"] is None else f"{row['percent']:.1f}%",
                row["status"],
            ]
            for row in nutrients
        ] or [["Sin datos", "--", "--", "--", "--", "--", "Sin referencia"]]
        table = axis.table(
            cellText=cells, colLabels=headers, cellLoc="center", colLoc="center",
            loc="upper center", colWidths=[0.21, 0.09, 0.12, 0.10, 0.12, 0.14, 0.15],
        )
        table.auto_set_font_size(False)
        table.set_fontsize(7.5)
        table.scale(1, 1.52)
        for (row_index, col_index), cell in table.get_celld().items():
            cell.set_edgecolor(BORDER)
            cell.set_linewidth(0.55)
            if row_index == 0:
                cell.set_facecolor(NAVY)
                cell.set_text_props(color="white", weight="bold")
            else:
                cell.set_facecolor("#FFFFFF" if row_index % 2 else SURFACE)
                cell.set_text_props(color=TEXT)
        for row_index, row in enumerate(nutrients, start=1):
            table[(row_index, 6)].set_text_props(color=row["color"], weight="bold")
            table[(row_index, 0)].set_text_props(ha="left", color=TEXT, weight="bold")

        _card(fig, 0.06, 0.085, 0.88, 0.045, face=SURFACE)
        fig.text(
            0.08, 0.104,
            "Criterio comparativo: Bajo < 80%  ·  Adecuado 80–120%  ·  Alto > 120% del objetivo.",
            fontsize=7.5, color=MUTED, va="center",
        )
        _save(pdf, fig)

        # Página 3: gráficos legibles.
        fig = _page(3, "Perfil nutricional comparativo", "Las barras expresan el porcentaje alcanzado frente al objetivo")
        groups = [
            ([row for row in nutrients if not row["is_micro"]], "Macronutrientes"),
            ([row for row in nutrients if row["is_micro"]], "Micronutrientes"),
        ]
        positions = [(0.11, 0.55, 0.80, 0.27), (0.11, 0.17, 0.80, 0.27)]
        for (rows, title), position in zip(groups, positions):
            axis = fig.add_axes(position)
            axis.set_facecolor("white")
            axis.axvspan(80, 120, color="#E7F3EC", alpha=1, zorder=0)
            axis.axvline(100, color=OK, linewidth=0.9, linestyle="--", zorder=1)
            if rows:
                values = [min(max(row["percent"] or 0, 0), 160) for row in rows]
                axis.barh(
                    [row["symbol"] for row in rows], values,
                    color=[row["color"] for row in rows], height=0.48, zorder=2,
                )
                for pos, row in enumerate(rows):
                    label = "--" if row["percent"] is None else f"{row['percent']:.0f}%"
                    axis.text(min(values[pos] + 2.5, 164), pos, label, va="center", fontsize=7.5, color=TEXT)
            axis.set_xlim(0, 170)
            axis.set_title(title, loc="left", color=NAVY, weight="bold", fontsize=10, pad=10)
            axis.set_xlabel("Porcentaje respecto al objetivo", fontsize=7.5, color=MUTED, labelpad=6)
            axis.grid(axis="x", color=BORDER, linewidth=0.55, alpha=0.8, zorder=0)
            axis.spines[["top", "right", "left"]].set_visible(False)
            axis.spines["bottom"].set_color(BORDER)
            axis.tick_params(axis="both", labelsize=7.5, colors=TEXT, length=0)
            axis.invert_yaxis()

        fig.text(
            0.06, 0.105,
            _wrap("La zona sombreada representa el intervalo comparativo entre 80% y 120%. Los porcentajes deben interpretarse según cultivo, tejido muestreado y etapa fenológica.", 125),
            fontsize=7.5, color=MUTED, va="top",
        )
        _save(pdf, fig)

        # Página 4: concepto agronómico con flujo vertical controlado.
        fig = _page(4, "Interpretación agronómica", "Hallazgos principales y criterios para validación en campo")
        sections = []
        if low:
            sections.append((
                "Nutrientes por debajo del objetivo", LOW,
                "Se observan niveles bajos en " + ", ".join(f"{r['name']} ({r['symbol']})" for r in low) +
                ". Antes de corregir, verifique muestreo, etapa fenológica, raíces, humedad, pH y disponibilidad en suelo."
            ))
        if high:
            sections.append((
                "Nutrientes por encima del objetivo", HIGH,
                "Los valores altos corresponden a " + ", ".join(f"{r['name']} ({r['symbol']})" for r in high) +
                ". Revise aplicaciones recientes, concentración de la muestra y posibles antagonismos."
            ))
        if adequate:
            sections.append((
                "Nutrientes en rango comparativo", OK,
                "Se encuentran entre 80% y 120% del objetivo: " +
                ", ".join(f"{r['name']} ({r['symbol']})" for r in adequate) +
                ". Mantenga seguimiento junto con rendimiento y evolución temporal."
            ))
        if limiting:
            sections.append((
                "Factor potencialmente limitante", BLUE_DARK,
                f"{limiting['name']} ({limiting['symbol']}) registra la menor proporción relativa "
                f"({limiting['percent']:.1f}%). Puede actuar como limitante potencial, pero requiere confirmación en campo."
            ))
        if not sections:
            sections.append(("Información insuficiente", MUTED, "No existen valores comparables suficientes para emitir una interpretación relativa."))

        y = 0.835
        for title, color, body in sections:
            wrapped = _wrap(body, 108)
            lines = wrapped.count("\n") + 1
            height = 0.058 + lines * 0.018
            _card(fig, 0.06, y - height, 0.88, height, face="white")
            fig.patches.append(Rectangle((0.06, y - height), 0.006, height, transform=fig.transFigure, color=color))
            fig.text(0.085, y - 0.026, title.upper(), fontsize=7.5, color=color, weight="bold")
            fig.text(0.085, y - 0.052, wrapped, fontsize=8.2, color=TEXT, va="top", linespacing=1.45)
            y -= height + 0.022

        if notes and y > 0.17:
            wrapped = _wrap(notes, 108)
            fig.text(0.06, y - 0.005, "OBSERVACIONES", fontsize=8, color=NAVY, weight="bold")
            fig.text(0.06, y - 0.034, wrapped, fontsize=8.2, color=TEXT, va="top", linespacing=1.45)

        professional_name = _text(professional.get("name"), 100)
        license_value = _text(professional.get("license"), 80)
        if professional_name:
            fig.text(0.06, 0.10, "RESPONSABLE", fontsize=7, color=MUTED, weight="bold")
            fig.text(0.06, 0.077, professional_name, fontsize=8.5, color=TEXT, weight="bold")
            if license_value:
                fig.text(0.06, 0.058, f"Matrícula profesional: {license_value}", fontsize=7, color=MUTED)
        _save(pdf, fig)

    output.seek(0)
    return output

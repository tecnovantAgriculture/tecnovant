from flask import render_template, url_for

from app.core.controller import login_required

from . import agrovista as web

def get_dashboard_menu():
    """Define el menu superior en los templates"""
    return {
        "menu": [
            {"name": "Home", "url": url_for("core.index")},
            {"name": "Logout", "url": url_for("core.logout")},
            {"name": "Profile", "url": url_for("core.profile")},
        ]
    }

@web.route("/", methods=["GET"])
@login_required
def hello():
    context = {
        "dashboard": True,
        "title": "NDVI Tool",
        "description": "Herramienta para el analisis NDVI.",
        "author": "Johnny De Castro",
        "site_title": "Análisis de Imagenes",
        "data_menu": get_dashboard_menu(),
        "entity_name": "Reportes",
        "entity_name_lower": "reporte",
    }
    return render_template("agrovista/ndvi-tool.j2", **context)


@web.route("/secondary-objectives", methods=["GET"])
@login_required
def secondary_objectives():
    context = {
        "dashboard": True,
        "title": "Objetivos secundarios",
        "description": "Gestion primaria de objetivos secundarios para NDVI.",
        "author": "Johnny De Castro",
        "site_title": "Agrovista",
        "data_menu": get_dashboard_menu(),
        "entity_name": "Objetivos secundarios",
        "entity_name_lower": "objetivo secundario",
    }
    return render_template("agrovista/secondary-objectives.j2", **context)

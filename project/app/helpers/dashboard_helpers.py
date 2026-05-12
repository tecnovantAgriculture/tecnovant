"""Dashboard helpers - funciones compartidas para navegación y menús

Centraliza funciones duplicadas en múltiples módulos para mejorar mantenibilidad.
Creado durante auditoría técnica fase 3.
"""

from flask import url_for


def get_dashboard_menu():
    """Define el menú superior en los templates.

    Returns:
        dict: Estructura del menú con nombre y URL para cada item.

    Ejemplo:
        {
            "menu": [
                {"name": "Home", "url": "/dashboard"},
                {"name": "Logout", "url": "/logout"},
                {"name": "Profile", "url": "/profile"},
            ]
        }
    """
    return {
        "menu": [
            {"name": "Home", "url": url_for("core.dashboard")},
            {"name": "Logout", "url": url_for("core.logout")},
            {"name": "Profile", "url": url_for("core.profile")},
        ]
    }


def get_module_dashboard_menu(module_name=None):
    """Obtiene menú del dashboard con opciones específicas del módulo.

    Args:
        module_name (str, optional): Nombre del módulo para personalización.

    Returns:
        dict: Menú personalizado según el módulo.
    """
    base_menu = get_dashboard_menu()

    # Personalizaciones por módulo (si se implementan en el futuro)
    if module_name == "agrovista":
        # Podría agregar opciones específicas de Agrovista
        pass
    elif module_name == "foliage_report":
        # Podría agregar opciones específicas de reportes
        pass
    elif module_name == "media":
        # Podría agregar opciones específicas de media
        pass

    return base_menu

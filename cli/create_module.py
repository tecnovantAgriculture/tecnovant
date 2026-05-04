import argparse
import os
from pathlib import Path


def create_module_structure(name: str, include_api: bool, include_ui: bool):
    """Create module skeleton under project/app/modules."""
    base_path = Path("project/app/modules")
    module_path = base_path / name
    os.makedirs(module_path, exist_ok=True)

    lines = ["from flask import Blueprint", ""]
    lines.append(
        f"{name} = Blueprint(\"{name}\", __name__, url_prefix='/dashboard/{name}', template_folder='templates')"
    )
    if include_api:
        lines.append(
            f"{name}_api = Blueprint(\"{name}_api\", __name__, url_prefix='/api/{name}')"
        )
    lines.append("")
    imports = ["web_routes"]
    if include_api:
        imports.append("api_routes")
    lines.append(f"from . import {', '.join(imports)}")

    with open(module_path / "__init__.py", "w") as f:
        f.write("\n".join(lines) + "\n")

    if include_api:
        with open(module_path / "api_routes.py", "w") as f:
            f.write(
                f"from flask import jsonify\nfrom . import {name}_api as api\n\n\n@api.route('/ping', methods=['GET'])\ndef ping():\n    return jsonify(message='pong from {name} API')\n"
            )

    if include_ui:
        with open(module_path / "web_routes.py", "w") as f:
            f.write(
                f"from flask import render_template\nfrom . import {name} as web\n\n\n@web.route('/hello')\ndef hello():\n    return render_template('{name}/hello.j2')\n"
            )
        templates_path = module_path / "templates" / name
        os.makedirs(templates_path, exist_ok=True)
        with open(templates_path / "hello.j2", "w") as f:
            f.write(
                f"<h1>Hello from {name} UI!</h1>\n"
            )

    for filename in ["controller.py", "models.py", "schemas.py", "helpers.py"]:
        with open(module_path / filename, "w") as f:
            f.write("")

    print(f"✅ Módulo '{name}' creado en {module_path}")
    print(f"Agrega '{name}' a la lista MODULES en app/config.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Creador de módulos para YAFSK")
    parser.add_argument("name", help="Nombre del módulo")
    parser.add_argument(
        "--api", action="store_true", help="Incluir estructura de API"
    )
    parser.add_argument(
        "--ui", action="store_true", help="Incluir estructura de UI"
    )

    args = parser.parse_args()

    if not args.api and not args.ui:
        parser.error("Debes especificar al menos --api o --ui")

    create_module_structure(args.name, args.api, args.ui)

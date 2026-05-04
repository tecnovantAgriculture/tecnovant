from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app.core.models import User


def merge_dicts(original, new_values):
    """Merge two dictionaries in Jinja2."""
    if not isinstance(original, dict) or not isinstance(new_values, dict):
        return original
    merged = original.copy()  # Hacemos una copia para evitar modificar el original
    merged.update(new_values)
    return merged


def inject_user():
    user_id = None
    username = None
    rol = None

    try:
        # Verifica si hay un token JWT en la solicitud
        verify_jwt_in_request(optional=True)
        user_id = get_jwt_identity()
        if user_id:
            user = User.query.get(user_id)
            if user:
                username = user.username
                rol = user.role.value
    except Exception:
        pass  # Si no hay token o hay un error, simplemente pasa

    return {"user_id": user_id, "username": username, "rol": rol}

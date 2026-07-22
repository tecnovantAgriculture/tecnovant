import json
import os
from functools import lru_cache

from google.oauth2 import service_account


@lru_cache(maxsize=1)
def get_google_credentials():
    """Carga las credenciales de Google almacenadas en Railway."""

    credentials_json = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS_JSON"
    )

    if not credentials_json:
        raise RuntimeError(
            "No está configurada la variable "
            "GOOGLE_APPLICATION_CREDENTIALS_JSON"
        )

    try:
        credentials_info = json.loads(credentials_json)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS_JSON "
            f"no contiene un JSON válido: {error}"
        ) from error

    private_key = credentials_info.get("private_key")

    if not private_key:
        raise RuntimeError(
            "El JSON de Google no contiene private_key"
        )

    credentials_info["private_key"] = private_key.replace(
        "\\n",
        "\n",
    )

    credentials = (
        service_account.Credentials.from_service_account_info(
            credentials_info
        )
    )

    return credentials, credentials_info
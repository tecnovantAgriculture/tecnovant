from functools import lru_cache

from google.cloud import storage

from config.google_credentials import get_google_credentials


@lru_cache(maxsize=1)
def get_storage_client():
    """
    Crea y reutiliza el cliente de Google Cloud Storage.
    """

    google_credentials, credentials_info = (
        get_google_credentials()
    )

    storage_client = storage.Client(
        project=credentials_info["project_id"],
        credentials=google_credentials,
    )

    return storage_client
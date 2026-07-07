from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests


class GCPComputeError(RuntimeError):
    pass


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class GCPComputeConfig:
    project_id: str
    zone: str
    instance: str
    service_account_file: str
    operation_timeout_seconds: int = 600

    @classmethod
    def from_env(cls) -> "GCPComputeConfig":
        return cls(
            project_id=os.getenv("GCP_PROJECT_ID", "").strip(),
            zone=os.getenv("GCP_ZONE", "").strip(),
            instance=os.getenv("GCP_WEBODM_INSTANCE", "").strip(),
            service_account_file=os.getenv("GCP_SERVICE_ACCOUNT_FILE", "").strip(),
            operation_timeout_seconds=int(
                os.getenv("GCP_OPERATION_TIMEOUT_SECONDS", "600")
            ),
        )

    def validate(self) -> None:
        missing = [
            name
            for name, value in {
                "GCP_PROJECT_ID": self.project_id,
                "GCP_ZONE": self.zone,
                "GCP_WEBODM_INSTANCE": self.instance,
                "GCP_SERVICE_ACCOUNT_FILE": self.service_account_file,
            }.items()
            if not value
        ]
        if missing:
            raise GCPComputeError(
                "Faltan variables para controlar la VM: " + ", ".join(missing)
            )
        if not os.path.isfile(self.service_account_file):
            raise GCPComputeError(
                f"No existe GCP_SERVICE_ACCOUNT_FILE: {self.service_account_file}"
            )


class GCPComputeClient:
    def __init__(self, config: GCPComputeConfig | None = None) -> None:
        self.config = config or GCPComputeConfig.from_env()
        self.config.validate()
        self.base_url = (
            "https://compute.googleapis.com/compute/v1"
            f"/projects/{self.config.project_id}/zones/{self.config.zone}"
        )
        self.session = self._authorized_session()

    def _authorized_session(self):
        try:
            from google.auth.transport.requests import AuthorizedSession
            from google.oauth2 import service_account
        except ImportError as exc:
            raise GCPComputeError(
                "Falta instalar google-auth. Ejecuta pip install google-auth."
            ) from exc

        credentials = service_account.Credentials.from_service_account_file(
            self.config.service_account_file,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return AuthorizedSession(credentials)

    def instance(self) -> dict:
        response = self.session.get(
            f"{self.base_url}/instances/{self.config.instance}",
            timeout=60,
        )
        return self._json_response(response)

    def status(self) -> str:
        return self.instance().get("status", "UNKNOWN")

    def start_instance(self) -> None:
        status = self.status()
        if status == "RUNNING":
            return
        if status not in {"TERMINATED", "STOPPED"}:
            self.wait_for_status({"RUNNING", "TERMINATED", "STOPPED"})
            if self.status() == "RUNNING":
                return

        response = self.session.post(
            f"{self.base_url}/instances/{self.config.instance}/start",
            timeout=60,
        )
        operation = self._json_response(response)
        self.wait_for_operation(operation["name"])
        self.wait_for_status({"RUNNING"})

    def stop_instance(self) -> None:
        status = self.status()
        if status in {"TERMINATED", "STOPPED"}:
            return

        response = self.session.post(
            f"{self.base_url}/instances/{self.config.instance}/stop",
            timeout=60,
        )
        operation = self._json_response(response)
        self.wait_for_operation(operation["name"])
        self.wait_for_status({"TERMINATED", "STOPPED"})

    def wait_for_status(self, statuses: set[str]) -> None:
        deadline = time.time() + self.config.operation_timeout_seconds
        while time.time() < deadline:
            current = self.status()
            if current in statuses:
                return
            time.sleep(5)
        raise GCPComputeError(
            f"La VM no llego a estado {', '.join(sorted(statuses))}."
        )

    def wait_for_operation(self, operation_name: str) -> None:
        deadline = time.time() + self.config.operation_timeout_seconds
        url = f"{self.base_url}/operations/{operation_name}"
        while time.time() < deadline:
            response = self.session.get(url, timeout=60)
            operation = self._json_response(response)
            if operation.get("status") == "DONE":
                if "error" in operation:
                    raise GCPComputeError(str(operation["error"]))
                return
            time.sleep(5)
        raise GCPComputeError(f"La operacion {operation_name} no termino a tiempo.")

    @staticmethod
    def _json_response(response: requests.Response) -> dict:
        if not response.ok:
            detail = response.text[:800].strip()
            raise GCPComputeError(f"Google Compute HTTP {response.status_code}: {detail}")
        return response.json()

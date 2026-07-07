from __future__ import annotations

import json
import os
import time
from typing import BinaryIO, Iterable
from urllib.parse import urlparse, urlunparse

import requests


class WebODMError(RuntimeError):
    pass


class WebODMClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("WEBODM_URL", "http://host.docker.internal:8000").rstrip("/")
        self.username = os.getenv("WEBODM_USERNAME", "").strip()
        self.password = os.getenv("WEBODM_PASSWORD", "").strip()
        self.project_name = os.getenv("WEBODM_PROJECT_NAME", "Tecnovan").strip()
        self.timeout = int(os.getenv("WEBODM_REQUEST_TIMEOUT_SECONDS", "60"))
        self.upload_timeout = int(os.getenv("WEBODM_UPLOAD_TIMEOUT_SECONDS", "7200"))
        self.resize_to = os.getenv("WEBODM_RESIZE_TO", "").strip()
        self.session = requests.Session()
        self._token: str | None = None

    def orthophoto_options(self, profile: str | None = None) -> list[dict[str, str]]:
        """Options for 2D orthophotos, with a fast default for field operations."""
        selected_profile = profile or os.getenv("WEBODM_PROCESSING_PROFILE", "fast_2d")
        profiles = {
            "fast_2d": {
                "fast-orthophoto": "true",
                "feature-quality": "medium",
                "pc-quality": "lowest",
                "matcher-neighbors": "12",
                "matcher-order": "12",
                "min-num-features": "10000",
                "orthophoto-resolution": "5",
            },
            "balanced_2d": {
                "fast-orthophoto": "true",
                "feature-quality": "high",
                "pc-quality": "medium",
                "matcher-neighbors": "20",
                "matcher-order": "20",
                "min-num-features": "20000",
                "orthophoto-resolution": "3",
            },
            "max_2d": {
                "feature-quality": "high",
                "pc-quality": "high",
                "matcher-neighbors": "24",
                "matcher-order": "24",
                "min-num-features": "25000",
                "orthophoto-resolution": "2.7",
            },
        }
        profile_options = profiles.get(selected_profile, profiles["fast_2d"]).copy()
        profile_options.update(
            {
                "skip-3dmodel": "true",
                "skip-report": "true",
                "camera-lens": os.getenv("WEBODM_CAMERA_LENS", "brown"),
                "use-fixed-camera-params": os.getenv("WEBODM_USE_FIXED_CAMERA_PARAMS", "true"),
                "sfm-algorithm": os.getenv("WEBODM_SFM_ALGORITHM", "triangulation"),
                "force-gps": os.getenv("WEBODM_FORCE_GPS", "true"),
                "gps-accuracy": os.getenv("WEBODM_GPS_ACCURACY", "3"),
                "matcher-type": os.getenv("WEBODM_MATCHER_TYPE", "flann"),
                "orthophoto-cutline": os.getenv("WEBODM_ORTHOPHOTO_CUTLINE", "true"),
            }
        )

        env_overrides = {
            "feature-quality": os.getenv("WEBODM_FEATURE_QUALITY"),
            "pc-quality": os.getenv("WEBODM_PC_QUALITY"),
            "matcher-neighbors": os.getenv("WEBODM_MATCHER_NEIGHBORS"),
            "matcher-order": os.getenv("WEBODM_MATCHER_ORDER"),
            "min-num-features": os.getenv("WEBODM_MIN_NUM_FEATURES"),
            "orthophoto-resolution": os.getenv("WEBODM_ORTHOPHOTO_RESOLUTION"),
            "orthophoto-cutline": os.getenv("WEBODM_ORTHOPHOTO_CUTLINE"),
            "force-gps": os.getenv("WEBODM_FORCE_GPS"),
        }
        for name, value in env_overrides.items():
            if value:
                profile_options[name] = value

        return [
            {"name": name, "value": value}
            for name, value in profile_options.items()
        ]

    def _headers(self) -> dict[str, str]:
        if self._token is None:
            self.authenticate()
        return {"Authorization": f"JWT {self._token}"}

    def authenticate(self) -> None:
        if not self.username or not self.password:
            raise WebODMError("Faltan WEBODM_USERNAME o WEBODM_PASSWORD.")
        response = self._request(
            "POST",
            "/api/token-auth/",
            json={"username": self.username, "password": self.password},
            timeout=self.timeout,
        )
        token = response.json().get("token")
        if not token:
            raise WebODMError("WebODM no retorno token de autenticacion.")
        self._token = token

    def wait_until_ready(self, timeout_seconds: int | None = None) -> None:
        deadline = time.time() + (
            timeout_seconds or int(os.getenv("WEBODM_READY_TIMEOUT_SECONDS", "900"))
        )
        last_error = None
        while time.time() < deadline:
            try:
                self.authenticate()
                return
            except Exception as exc:
                last_error = exc
                time.sleep(10)
        raise WebODMError(f"WebODM no respondio a tiempo: {last_error}")

    def processing_nodes(self) -> list[dict]:
        response = self._request(
            "GET",
            "/api/processingnodes/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return response.json()

    def get_or_create_project(self) -> dict:
        response = self._request(
            "GET",
            "/api/projects/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        for project in response.json():
            if project.get("name") == self.project_name:
                return project

        response = self._request(
            "POST",
            "/api/projects/",
            headers=self._headers(),
            json={
                "name": self.project_name,
                "description": "Procesamiento de ortofotos desde TecnoAgro.",
            },
            timeout=self.timeout,
        )
        return response.json()

    def create_task(
        self,
        *,
        project_id: int,
        name: str,
        images: Iterable[tuple[str, BinaryIO, str]],
        processing_node_id: int | None,
        options: Iterable[dict[str, str]] | None = None,
    ) -> dict:
        files = [
            ("images", (filename, stream, content_type))
            for filename, stream, content_type in images
        ]
        data: dict[str, str] = {"name": name}
        if processing_node_id is not None:
            data["processing_node"] = str(processing_node_id)
        if self.resize_to:
            data["resize_to"] = self.resize_to
        if options:
            data["options"] = json.dumps(list(options))

        response = self._request(
            "POST",
            f"/api/projects/{project_id}/tasks/",
            headers=self._headers(),
            data=data,
            files=files,
            timeout=self.upload_timeout,
        )
        return response.json()

    def task(self, project_id: int, task_id: str) -> dict:
        response = self._request(
            "GET",
            f"/api/projects/{project_id}/tasks/{task_id}/",
            headers=self._headers(),
            timeout=self.timeout,
        )
        return response.json()

    def restart_task(
        self,
        project_id: int,
        task_id: str,
        options: Iterable[dict[str, str]] | None = None,
    ) -> dict:
        data: dict[str, str] = {}
        if options:
            data["options"] = json.dumps(list(options))

        try:
            response = self._request(
                "POST",
                f"/api/projects/{project_id}/tasks/{task_id}/restart/",
                headers=self._headers(),
                data=data,
                timeout=self.timeout,
            )
        except WebODMError:
            if not options:
                raise
            response = self._request(
                "POST",
                f"/api/projects/{project_id}/tasks/{task_id}/restart/",
                headers=self._headers(),
                timeout=self.timeout,
            )

        if response.text.strip():
            return response.json()
        return self.task(project_id, task_id)

    def delete_task(self, project_id: int, task_id: str) -> None:
        self._request(
            "DELETE",
            f"/api/projects/{project_id}/tasks/{task_id}/",
            headers=self._headers(),
            timeout=self.timeout,
        )

    def download_asset(self, project_id: int, task_id: str, asset: str) -> requests.Response:
        download_timeout = int(os.getenv("WEBODM_DOWNLOAD_TIMEOUT_SECONDS", "7200"))
        return self._request(
            "GET",
            f"/api/projects/{project_id}/tasks/{task_id}/download/{asset}",
            headers=self._headers(),
            timeout=download_timeout,
            stream=True,
        )

    def task_browser_url(self, project_id: int, task_id: str) -> str:
        public_base = os.getenv("WEBODM_PUBLIC_URL", "").strip() or self.base_url
        parsed = urlparse(public_base)
        if parsed.hostname == "host.docker.internal":
            netloc = "localhost"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            public_base = urlunparse(parsed._replace(netloc=netloc))
        return f"{public_base.rstrip('/')}/dashboard/#/projects/{project_id}/tasks/{task_id}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            response = self.session.request(method, f"{self.base_url}{path}", **kwargs)
        except requests.RequestException as exc:
            raise WebODMError(f"No fue posible conectar con WebODM: {exc}") from exc

        if not response.ok:
            detail = response.text[:800].strip()
            if path == "/api/token-auth/" and response.status_code in {400, 401}:
                raise WebODMError(
                    "Usuario o contrasena de WebODM incorrectos. "
                    "Revisa WEBODM_USERNAME y WEBODM_PASSWORD."
                )
            raise WebODMError(f"WebODM HTTP {response.status_code}: {detail}")
        return response

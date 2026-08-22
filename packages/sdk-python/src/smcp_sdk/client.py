from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen
from uuid import uuid4

Transport = Callable[
    [str, str, Mapping[str, str], bytes | None, float],
    tuple[int, Mapping[str, str], bytes],
]


class SmcpProblem(RuntimeError):
    def __init__(self, status: int, body: object) -> None:
        problem = body if isinstance(body, dict) else {}
        self.status = status
        self.type = str(problem.get("type", "about:blank"))
        self.request_id = problem.get("request_id")
        self.body = body
        message = (
            problem.get("detail")
            or problem.get("title")
            or f"SMCP request failed with {status}"
        )
        super().__init__(str(message))


class SmcpClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = 30,
        transport: Transport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.transport = transport or _urllib_transport

    def codecs(self) -> dict[str, Any]:
        return self._request("GET", "v1/codecs")

    def models(self) -> dict[str, Any]:
        return self._request("GET", "v1/models")

    def presign_upload(
        self, payload: Mapping[str, object], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return self._request("POST", "v1/uploads/presign", payload, idempotency_key)

    def create_compression(
        self, payload: Mapping[str, object], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return self._request("POST", "v1/compressions", payload, idempotency_key)

    def compression(self, resource_id: str) -> dict[str, Any]:
        return self._request("GET", f"v1/compressions/{quote(resource_id, safe='')}")

    def create_capsule_plan(
        self, payload: Mapping[str, object], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return self._request("POST", "v1/capsule-plans", payload, idempotency_key)

    def create_capsule(
        self, payload: Mapping[str, object], *, idempotency_key: str | None = None
    ) -> dict[str, Any]:
        return self._request("POST", "v1/capsules", payload, idempotency_key)

    def capsule(self, resource_id: str) -> dict[str, Any]:
        return self._request("GET", f"v1/capsules/{quote(resource_id, safe='')}")

    def verify_capsule(self, project_id: str, capsule_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "v1/capsules/verify",
            {"project_id": project_id, "capsule_id": capsule_id},
        )

    def project_usage(self, project_id: str) -> dict[str, Any]:
        return self._request("GET", f"v1/projects/{quote(project_id, safe='')}/usage")

    def webhooks(self, project_id: str) -> dict[str, Any]:
        query = urlencode({"project_id": project_id})
        return self._request("GET", f"v1/webhooks?{query}")

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        headers = {
            "accept": "application/json",
            "authorization": f"Bearer {self.api_key}",
        }
        body = None
        if payload is not None:
            headers["content-type"] = "application/json"
            body = json.dumps(payload, separators=(",", ":")).encode()
        if method != "GET":
            headers["idempotency-key"] = idempotency_key or str(uuid4())
        status, _, response = self.transport(
            method,
            urljoin(self.base_url, path),
            headers,
            body,
            self.timeout_seconds,
        )
        decoded: object = json.loads(response) if response else {}
        if not 200 <= status < 300:
            raise SmcpProblem(status, decoded)
        if not isinstance(decoded, dict):
            raise ValueError("SMCP response must be a JSON object")
        return decoded


def _urllib_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout: float,
) -> tuple[int, Mapping[str, str], bytes]:
    request = Request(url, data=body, headers=dict(headers), method=method)  # noqa: S310
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - caller configures API origin
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers.items()), error.read()

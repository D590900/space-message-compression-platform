from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from smcp_sdk import SmcpClient, SmcpProblem


def test_mutation_adds_auth_and_idempotency() -> None:
    captured: dict[str, object] = {}

    def transport(
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        captured.update(method=method, url=url, headers=headers, body=body, timeout=timeout)
        return 202, {}, b'{"id":"job_1"}'

    client = SmcpClient("https://api.example.com", "smcp_secret", transport=transport)
    result = client.create_compression(
        {"project_id": "project", "source_object_id": "source"},
        idempotency_key="request-0001",
    )

    assert result == {"id": "job_1"}
    assert captured["url"] == "https://api.example.com/v1/compressions"
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer smcp_secret"
    assert headers["idempotency-key"] == "request-0001"


def test_problem_details_is_typed() -> None:
    def transport(
        _method: str,
        _url: str,
        _headers: Mapping[str, str],
        _body: bytes | None,
        _timeout: float,
    ) -> tuple[int, Mapping[str, str], bytes]:
        return 429, {}, json.dumps(
            {
                "type": "urn:smcp:problem:quota-exceeded",
                "title": "Quota exceeded",
                "request_id": "request_1",
            }
        ).encode()

    client = SmcpClient("https://api.example.com", "smcp_secret", transport=transport)
    with pytest.raises(SmcpProblem) as raised:
        client.codecs()
    assert raised.value.status == 429
    assert raised.value.type == "urn:smcp:problem:quota-exceeded"
    assert raised.value.request_id == "request_1"

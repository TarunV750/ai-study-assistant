"""Small Signature Version 4 HTTP adapter for OpenSearch Serverless."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse


class OpenSearchRequestError(RuntimeError):
    """An OpenSearch request returned an unsuccessful HTTP status."""

    def __init__(self, status_code: int, response_body: str) -> None:
        super().__init__(f"OpenSearch returned HTTP {status_code}: {response_body}")
        self.status_code = status_code
        self.response_body = response_body


def signed_json_request(
    *,
    endpoint: str,
    region: str,
    method: str,
    path: str,
    body: bytes = b"",
    content_type: str = "application/json",
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Send one SigV4-signed request using libraries included in Lambda Python."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.session import Session

    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
        raise ValueError("The OpenSearch endpoint must be an HTTPS origin.")
    if not path or any(character in path for character in ("?", "#")):
        raise ValueError("The OpenSearch path is invalid.")

    url = f"{endpoint.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Content-Type": content_type,
        "x-amz-content-sha256": hashlib.sha256(body).hexdigest(),
    }
    credentials = Session().get_credentials()
    if credentials is None:
        raise RuntimeError("AWS credentials are unavailable for OpenSearch signing.")
    aws_request = AWSRequest(method=method, url=url, data=body, headers=headers)
    SigV4Auth(credentials.get_frozen_credentials(), "aoss", region).add_auth(aws_request)
    request = urllib.request.Request(
        url=url,
        data=body or None,
        headers=dict(aws_request.headers.items()),
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")[:1_000]
        raise OpenSearchRequestError(error.code, response_body) from error

    if not payload:
        return {}
    try:
        parsed_body = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("OpenSearch returned a non-JSON response.") from error
    if not isinstance(parsed_body, dict):
        raise RuntimeError("OpenSearch returned an invalid response.")
    return parsed_body

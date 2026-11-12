#!/usr/bin/env python3
"""Live, non-destructive API smoke test for a deployed CourseLens stack."""

from __future__ import annotations

import json
import os
import re
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(base_url: str, path: str, *, method: str = "GET", body=None, headers=None):
    encoded = None if body is None else json.dumps(body).encode("utf-8")
    request_headers = dict(headers or {})
    if encoded is not None:
        request_headers["Content-Type"] = "application/json"
    req = Request(
        f"{base_url.rstrip('/')}{path}",
        data=encoded,
        headers=request_headers,
        method=method,
    )
    try:
        with urlopen(req, timeout=35) as response:
            raw = response.read()
            payload = json.loads(raw) if raw else None
            normalized_headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, normalized_headers, payload
    except HTTPError as error:
        raw = error.read()
        payload = json.loads(raw) if raw else None
        raise AssertionError(f"{method} {path} returned {error.code}: {payload}") from error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    base_url = os.environ.get("API_ENDPOINT", "").strip()
    require(base_url.startswith("https://"), "API_ENDPOINT must be an HTTPS origin.")
    origin = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")

    status, _, listing = request(base_url, "/documents")
    require(status == 200 and isinstance(listing.get("documents"), list), "Document listing contract failed.")
    indexed = [item for item in listing["documents"] if item.get("status") == "INDEXED"]
    require(indexed, "At least one indexed document is required for the smoke test.")

    document_id = os.environ.get("DOCUMENT_ID") or indexed[0]["documentId"]
    document = next((item for item in indexed if item.get("documentId") == document_id), None)
    require(document is not None, "DOCUMENT_ID must reference an indexed document.")

    status, headers, detail = request(base_url, f"/documents/{document_id}")
    require(status == 200 and detail.get("status") == "INDEXED", "Document detail contract failed.")
    require(headers.get("x-content-type-options") == "nosniff", "Safe response header is missing.")

    status, cors_headers, _ = request(
        base_url,
        "/ask",
        method="OPTIONS",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    require(status == 204, "CORS preflight failed.")
    require(cors_headers.get("access-control-allow-origin") == origin, "CORS origin is not exact.")

    status, _, upload = request(
        base_url,
        "/upload-url",
        method="POST",
        body={"filename": "smoke-test.pdf", "fileSize": 1024, "contentType": "application/pdf"},
    )
    require(status == 200 and upload.get("upload", {}).get("method") == "POST", "Upload instruction contract failed.")
    require(upload.get("expiresIn") == 300, "Presigned upload expiry changed unexpectedly.")

    filename = document.get("filename", "course material")
    filename_topic = re.sub(r"[^A-Za-z0-9]+", " ", filename.rsplit(".", 1)[0]).strip()
    default_question = f"What does this document explain about {filename_topic or 'the course material'}?"
    question = os.environ.get("SMOKE_QUESTION", default_question)
    status, _, answer = request(
        base_url,
        "/ask",
        method="POST",
        body={"question": question, "documentIds": [document_id]},
    )
    require(status == 200 and isinstance(answer.get("answer"), str), "Question-answer contract failed.")
    require(answer.get("noAnswer") is False and answer.get("sources"), "Smoke question did not produce a cited answer.")

    status, _, study = request(
        base_url,
        "/study",
        method="POST",
        body={"mode": "study-guide", "documentIds": [document_id], "count": 6, "questionType": "mixed"},
    )
    require(status == 200 and study.get("noAnswer") is False, "Study guide generation failed.")
    require(isinstance(study.get("content"), str) and study.get("sources"), "Study guide citations are missing.")

    print(
        json.dumps(
            {
                "result": "PASS",
                "document": document.get("filename", "document.pdf"),
                "checks": [
                    "document-list",
                    "document-detail",
                    "safe-headers",
                    "cors",
                    "presigned-upload",
                    "cited-answer",
                    "cited-study-guide",
                ],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, TimeoutError) as error:
        print(f"E2E smoke test failed: {error}", file=sys.stderr)
        raise SystemExit(1)

"""Serves the built website from the API process, for hosts that run a single container.
The normal deployment uses nginx instead, with the same Content-Security-Policy."""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

from app.api.rate_limit import limiter

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
)
# Built files carry a content hash in their name, so they never change. Everything else,
# above all the page itself, must be checked on every visit or a browser keeps an old
# page that points at files the next deploy removed.
IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


def mount_site(app: FastAPI, root: Path) -> None:
    """Call after every other route is registered, because this one matches any path."""
    root = root.resolve()

    @app.middleware("http")
    async def content_security_policy(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        return response

    @app.get("/{path:path}", include_in_schema=False)
    @limiter.exempt
    def site(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        candidate = (root / path).resolve()
        if path and candidate.is_relative_to(root) and candidate.is_file():
            cache = IMMUTABLE if path.startswith("assets/") else REVALIDATE
            return FileResponse(candidate, headers={"Cache-Control": cache})
        if path.startswith("assets/"):
            # Answering with the page would make the browser reject it as a script.
            raise HTTPException(status.HTTP_404_NOT_FOUND)
        # Unknown paths are routes inside the single-page app.
        return FileResponse(root / "index.html", headers={"Cache-Control": REVALIDATE})

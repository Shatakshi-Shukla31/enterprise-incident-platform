import hmac
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api.rate_limit import limiter
from app.api.v1 import ai, auth, incidents, ops, users
from app.core.config import get_settings
from app.core.logging import configure_logging, request_id_var
from app.db.session import get_engine
from app.ml import inference
from app.services.errors import ServiceError
from app.site import mount_site
from app.workers import scheduler

settings = get_settings()
logger = logging.getLogger("app.request")

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("http_request_seconds", "HTTP request latency", ["route"])


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    stop_scheduler = threading.Event()
    if settings.single_process:
        scheduler.start(stop_scheduler)
    yield
    stop_scheduler.set()
    get_engine().dispose()


app = FastAPI(
    title="Incident Management Platform",
    version="1.0.0",
    description="Incident management with ML triage and evidence-grounded troubleshooting.",
    lifespan=lifespan,
    # The schema maps the whole attack surface, so production does not publish it.
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None,
    openapi_url=None if settings.environment == "production" else "/openapi.json",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def observe(request: Request, call_next) -> Response:
    request_id = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error")
        response = JSONResponse({"detail": "Internal server error"}, status_code=500)
    duration = time.perf_counter() - started
    route = getattr(request.scope.get("route"), "path", "unmatched")
    REQUESTS.labels(request.method, route, response.status_code).inc()
    LATENCY.labels(route).observe(duration)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    logger.info(
        "request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 1),
        },
    )
    request_id_var.reset(token)
    return response


@app.exception_handler(ServiceError)
async def handle_service_error(_: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


for module in (auth, users, incidents, ops, ai):
    app.include_router(module.router, prefix=settings.api_prefix)


@app.get("/health", tags=["system"])
@limiter.exempt
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
@limiter.exempt
def ready() -> JSONResponse:
    checks: dict[str, object] = {"models": inference.status()}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        logger.exception("Readiness check failed")
        checks["database"] = "unavailable"
    healthy = checks["database"] == "ok"
    return JSONResponse(checks, status_code=200 if healthy else 503)


@app.get("/metrics", include_in_schema=False)
@limiter.exempt
def metrics(request: Request) -> Response:
    expected = settings.metrics_token
    supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if settings.static_dir:
    mount_site(app, settings.static_dir)

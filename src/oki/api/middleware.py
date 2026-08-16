from time import perf_counter

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from oki.api.errors import (
    CORRELATION_ID_HEADER,
    generate_correlation_id,
    internal_server_error_response,
    parse_correlation_id,
)

_REQUEST_LOGGER = structlog.get_logger("oki.request")


def _request_header(scope: Scope, name: bytes) -> str | None:
    for header_name, value in scope.get("headers", []):
        if header_name.lower() == name:
            return value.decode("latin-1")
    return None


class CorrelationMiddleware:
    """Attach a bounded correlation identifier to every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = _request_header(scope, CORRELATION_ID_HEADER.lower().encode("ascii"))
        correlation_id = parse_correlation_id(supplied) or generate_correlation_id()
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[CORRELATION_ID_HEADER] = correlation_id
            await send(message)

        await self.app(scope, receive, send_with_correlation)


class ProblemMiddleware:
    """Translate unexpected HTTP failures into safe RFC 9457 responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def track_response(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, track_response)
        except Exception as exception:
            request = Request(scope, receive=receive)
            correlation_id = parse_correlation_id(
                str(getattr(request.state, "correlation_id", "")),
            )
            if correlation_id is None:
                correlation_id = generate_correlation_id()
                request.state.correlation_id = correlation_id
            import traceback
            print(f"\n[500 ERROR] {scope['method']} {scope['path']}: {type(exception).__name__}: {exception}")
            traceback.print_exc()
            _REQUEST_LOGGER.exception(
                "unhandled_http_exception",
                method=scope["method"],
                path=scope["path"],
                correlation_id=correlation_id,
                exception_type=type(exception).__name__,
            )
            if response_started:
                raise
            response = internal_server_error_response(request)
            await response(scope, receive, send)


class StructuredRequestMiddleware:
    """Emit one structured completion event for every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started_at = perf_counter()
        status_code = 500

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            state = scope.get("state", {})
            _REQUEST_LOGGER.info(
                "http_request_completed",
                method=scope["method"],
                path=scope["path"],
                status_code=status_code,
                duration_ms=round((perf_counter() - started_at) * 1000, 3),
                correlation_id=state.get("correlation_id"),
            )


def install_middleware(app: FastAPI) -> None:
    """Install correlation, problem, CORS, and structured request middleware.

    Order matters: Starlette executes middleware LIFO (last added = outermost).
    CORS must wrap Problem so that exception responses still get CORS headers.
    """

    # Innermost: catches exceptions near the route handler
    app.add_middleware(ProblemMiddleware)

    # Wraps Problem: adds CORS headers to ALL responses (including 500s)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(StructuredRequestMiddleware)
    app.add_middleware(CorrelationMiddleware)

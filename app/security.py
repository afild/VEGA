from collections.abc import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
UPLOAD_PATH = "/api/contracts/upload"
MULTIPART_OVERHEAD_BYTES = 1024 * 1024

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' https://cdn.jsdelivr.net",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    )
)


def parse_csv_setting(value: str) -> list[str]:
    """Converte uma configuração CSV em valores únicos e não vazios."""
    return list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))


def _normalize_origin(value: str) -> str:
    return value.strip().rstrip("/").casefold()


def _add_security_headers(response: Response, api_request: bool) -> Response:
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    )
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    if api_request:
        response.headers.setdefault("Cache-Control", "no-store")
    return response


class LocalSecurityMiddleware(BaseHTTPMiddleware):
    """Protege a aplicação local contra requisições cross-site e uploads excessivos."""

    def __init__(
        self,
        app,
        *,
        allowed_origins: Iterable[str],
        max_upload_bytes: int,
    ) -> None:
        super().__init__(app)
        self.allowed_origins = {
            _normalize_origin(origin) for origin in allowed_origins if origin.strip()
        }
        self.max_upload_request_bytes = max_upload_bytes + MULTIPART_OVERHEAD_BYTES

    async def dispatch(self, request: Request, call_next) -> Response:
        api_request = request.url.path.startswith("/api/")

        if request.method not in SAFE_METHODS:
            rejection = self._reject_cross_site_request(request)
            if rejection is not None:
                return _add_security_headers(rejection, api_request)

        if request.method == "POST" and request.url.path == UPLOAD_PATH:
            rejection = self._reject_oversized_request(request)
            if rejection is not None:
                return _add_security_headers(rejection, api_request)

        response = await call_next(request)
        return _add_security_headers(response, api_request)

    def _reject_cross_site_request(self, request: Request) -> Response | None:
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site", "").casefold()

        if not origin:
            if fetch_site == "cross-site":
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Requisição cross-site não permitida."},
                )
            return None

        request_origin = _normalize_origin(
            f"{request.url.scheme}://{request.headers.get('host', '')}"
        )
        normalized_origin = _normalize_origin(origin)
        if normalized_origin == request_origin or normalized_origin in self.allowed_origins:
            return None

        return JSONResponse(
            status_code=403,
            content={"detail": "Origem não permitida para esta operação."},
        )

    def _reject_oversized_request(self, request: Request) -> Response | None:
        content_length = request.headers.get("content-length")
        if content_length is None:
            return None

        try:
            request_size = int(content_length)
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"detail": "Cabeçalho Content-Length inválido."},
            )

        if request_size < 0:
            return JSONResponse(
                status_code=400,
                content={"detail": "Cabeçalho Content-Length inválido."},
            )

        if request_size > self.max_upload_request_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": "Arquivo de contrato excede o limite configurado."},
            )
        return None

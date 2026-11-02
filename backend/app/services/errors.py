class ServiceError(Exception):
    """A business rule failure. The API layer maps these to HTTP responses."""

    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFound(ServiceError):
    status_code = 404


class Forbidden(ServiceError):
    status_code = 403


class Conflict(ServiceError):
    status_code = 409


class Unavailable(ServiceError):
    status_code = 503

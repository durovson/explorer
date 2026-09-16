class DomainError(RuntimeError):
    """Expected business-rule error safe to show to a user."""


class ConcurrentUpdateError(DomainError):
    pass


class PaymentProviderTemporaryError(RuntimeError):
    pass


class FragmentRejectedError(RuntimeError):
    """Fragment definitively rejected a request before fulfillment."""

    def __init__(
        self,
        message: str,
        *,
        response: dict | None = None,
        http_status: int | None = None,
    ):
        super().__init__(message)
        self.response = response
        self.http_status = http_status


class FragmentAmbiguousError(RuntimeError):
    """Fragment outcome is unknown and must never be retried automatically."""

    def __init__(
        self,
        message: str,
        *,
        response: dict | None = None,
        http_status: int | None = None,
    ):
        super().__init__(message)
        self.response = response
        self.http_status = http_status

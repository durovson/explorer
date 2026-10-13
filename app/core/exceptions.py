class DomainError(RuntimeError):
    """Expected business-rule error safe to show to a user."""


class ConcurrentUpdateError(DomainError):
    pass


class PaymentProviderTemporaryError(RuntimeError):
    pass


class FragmentRejectedError(RuntimeError):
    """Provider definitively rejected a request before fulfillment."""

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


class FragmentTemporaryError(RuntimeError):
    """Provider failed before broadcast, so the purchase is safe to retry."""

    def __init__(
        self,
        message: str,
        *,
        response: dict | None = None,
        http_status: int | None = None,
        retry_after_seconds: int = 60,
    ):
        super().__init__(message)
        self.response = response
        self.http_status = http_status
        self.retry_after_seconds = retry_after_seconds


class FragmentAmbiguousError(RuntimeError):
    """Provider outcome is unknown and must never be retried automatically."""

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

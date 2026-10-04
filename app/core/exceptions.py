class DomainError(RuntimeError):
    """Expected business-rule error safe to show to a user."""


class ConcurrentUpdateError(DomainError):
    pass


class PaymentProviderTemporaryError(RuntimeError):
    pass


class ProviderRejectedError(RuntimeError):
    """A fulfillment provider definitively rejected an operation."""

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


class ProviderAmbiguousError(RuntimeError):
    """Provider outcome may have side effects and must not be retried automatically."""

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


class FragmentRejectedError(ProviderRejectedError):
    """Fragment definitively rejected a request before fulfillment."""


class FragmentAmbiguousError(ProviderAmbiguousError):
    """Fragment outcome is unknown and must never be retried automatically."""


class MarketappRejectedError(ProviderRejectedError):
    """Marketapp rejected an operation without a successful blockchain send."""


class MarketappAmbiguousError(ProviderAmbiguousError):
    """Marketapp/TON outcome is unknown and needs manual reconciliation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.config import Settings
from app.core.enums import Currency, ProductType
from app.core.exceptions import FragmentAmbiguousError, FragmentRejectedError
from app.models.entities import Order


@dataclass(frozen=True, slots=True)
class FragmentResult:
    payload: dict[str, Any]
    http_status: int
    external_order_id: str


class FragmentService:
    """Current fragment-api.com OpenAPI adapter using a Fragment Connection JWT."""

    TERMINAL_SUCCESS = frozenset({"COMPLETED"})
    TERMINAL_FAILURE = frozenset({"FAILED"})
    PENDING = frozenset({"CREATED", "PENDING", "BLOCKCHAIN_SENT"})

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=settings.FRAGMENT_TIMEOUT_SECONDS)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"JWT {self._settings.FRAGMENT_JWT_TOKEN}",
            "Accept": "application/json",
        }

    async def close(self) -> None:
        await self._client.aclose()

    async def user_info(self, recipient: str) -> dict[str, Any]:
        username = quote(recipient.lstrip("@"), safe="")
        try:
            response = await self._client.get(
                f"{self._settings.FRAGMENT_BASE_URL.rstrip('/')}/misc/user/{username}/",
                headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("Fragment preflight temporarily unavailable") from exc
        if response.status_code == 404:
            raise ValueError("username не найден")
        if response.is_error:
            raise RuntimeError(f"Fragment preflight HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("Fragment preflight returned invalid JSON") from exc
        if not isinstance(data, dict) or not data.get("username"):
            raise RuntimeError("Fragment preflight returned invalid user data")
        return data

    async def purchase(self, order: Order, idempotency_key: str) -> FragmentResult:
        if order.product_type is ProductType.STARS:
            path = "order/stars/"
            payload: dict[str, Any] = {
                "username": order.recipient.lstrip("@"),
                "quantity": order.stars_amount,
                "show_sender": False,
            }
        else:
            path = "order/premium/"
            payload = {
                "username": order.recipient.lstrip("@"),
                "months": order.premium_months,
                "show_sender": False,
            }
        payload["currency"] = "ton" if order.currency is Currency.TON else "usdt_ton"
        headers = {**self._headers, "Idempotency-Key": idempotency_key}
        try:
            response = await self._client.post(
                f"{self._settings.FRAGMENT_BASE_URL.rstrip('/')}/{path}",
                json=payload,
                headers=headers,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise FragmentAmbiguousError(
                f"Fragment request outcome is unknown: {exc}"
            ) from exc
        data = self._response_json(response, request_sent=True)
        result = self._classify(data, response.status_code)
        if result is not None:
            return result

        external_id = str(data.get("id") or "")
        if not external_id:
            raise FragmentAmbiguousError(
                "Fragment returned a non-terminal order without id",
                response=data,
                http_status=response.status_code,
            )
        # Synchronous requests should normally be terminal. Poll briefly if the
        # provider returns PENDING/BLOCKCHAIN_SENT.
        for _ in range(15):
            await asyncio.sleep(2)
            checked = await self._check_order(external_id)
            result = self._classify(checked, 200)
            if result is not None:
                return result
        raise FragmentAmbiguousError(
            f"Fragment order {external_id} stayed non-terminal",
            response=data,
            http_status=response.status_code,
        )

    async def _check_order(self, external_id: str) -> dict[str, Any]:
        try:
            response = await self._client.get(
                f"{self._settings.FRAGMENT_BASE_URL.rstrip('/')}/order/"
                f"{quote(external_id, safe='')}/",
                headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise FragmentAmbiguousError(
                f"Could not reconcile Fragment order {external_id}: {exc}",
                response={"id": external_id},
            ) from exc
        return self._response_json(response, request_sent=True)

    def _response_json(
        self, response: httpx.Response, *, request_sent: bool
    ) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            error_type = (
                FragmentAmbiguousError if request_sent else FragmentRejectedError
            )
            raise error_type(
                "Fragment returned non-JSON data",
                http_status=response.status_code,
            ) from exc
        if not isinstance(data, dict):
            raise FragmentAmbiguousError(
                "Fragment returned invalid response shape",
                http_status=response.status_code,
            )
        if response.status_code >= 500:
            raise FragmentAmbiguousError(
                f"Fragment server error {response.status_code}",
                response=data,
                http_status=response.status_code,
            )
        if response.is_error:
            raise FragmentRejectedError(
                f"Fragment rejected order: {data}",
                response=data,
                http_status=response.status_code,
            )
        return data

    def _classify(
        self, data: dict[str, Any], http_status: int
    ) -> FragmentResult | None:
        status = str(data.get("status") or "").upper()
        external_id = str(data.get("id") or "")
        if status in self.TERMINAL_FAILURE or data.get("success") is False:
            raise FragmentRejectedError(
                f"Fragment order failed: {data.get('error') or status}",
                response=data,
                http_status=http_status,
            )
        if status in self.TERMINAL_SUCCESS and data.get("success") is not False:
            if not external_id:
                raise FragmentAmbiguousError(
                    "Completed Fragment response has no order id",
                    response=data,
                    http_status=http_status,
                )
            return FragmentResult(data, http_status, external_id)
        if status in self.PENDING:
            return None
        raise FragmentAmbiguousError(
            f"Unknown Fragment order status: {status or 'missing'}",
            response=data,
            http_status=http_status,
        )

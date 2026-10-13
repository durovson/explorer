from __future__ import annotations

import asyncio
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from ton_core import Address, NetworkGlobalID
from tonutils.clients import ToncenterClient
from tonutils.contracts import SeqnoGuard, WalletV4R2, WalletV5R1

from app.config import Settings
from app.services.payments import same_address


class SettlementService:
    """Move only the realized service margin out of the operational TON wallet."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._lock = asyncio.Lock()

    async def transfer_profit(self, order_id: UUID, amount: Decimal) -> str:
        atomic = int(
            (amount * Decimal("1000000000")).to_integral_value(rounding=ROUND_DOWN)
        )
        if atomic <= 0:
            raise ValueError("Service margin is too small to transfer")

        async with self._lock:
            client = ToncenterClient(
                network=NetworkGlobalID.MAINNET,
                api_key=self._settings.TONCENTER_API_KEY,
                rps_limit=self._settings.TONCENTER_RPS_LIMIT,
            )
            await client.connect()
            try:
                wallet_cls = (
                    WalletV5R1
                    if self._settings.MARKETAPP_WALLET_VERSION == "V5R1"
                    else WalletV4R2
                )
                wallet, _, _, _ = wallet_cls.from_mnemonic(
                    client, self._settings.MARKETAPP_WALLET_SEED
                )
                derived = wallet.address.to_str(is_bounceable=False)
                if not same_address(derived, self._settings.TON_RECEIVER_ADDRESS):
                    raise RuntimeError(
                        "Operational wallet derived from the seed does not match the payment address"
                    )

                guard = SeqnoGuard(wallet, timeout=45.0, poll_interval=1.5)
                message = await guard.transfer(
                    destination=Address(self._settings.SERVICE_PROFIT_ADDRESS),
                    amount=atomic,
                    body=f"STRS.TG fee #{str(order_id)[:8]}",
                )
                return str(message.normalized_hash)
            finally:
                await client.close()

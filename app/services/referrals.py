from app.models.entities import ReferralStats
from app.repositories.users import UserRepository
from datetime import UTC, datetime
from app.services.payments import normalize_ton_address
import base64
import binascii
import re


class ReferralService:
    """GRNT commission shares and reserved withdrawal ledger; operator settles payouts."""

    def __init__(self, users: UserRepository):
        self._users = users

    async def assign(self, referred_id: int, referrer_id: int) -> bool:
        if referred_id == referrer_id or referrer_id <= 0:
            return False
        return await self._users.assign_referrer(referred_id, referrer_id)

    async def stats(self, telegram_id: int, bot=None) -> ReferralStats:
        profile = await self._users.referral_profile(telegram_id)
        if bot and profile.get("holder_chat_id"):
            member = await bot.get_chat_member(profile["holder_chat_id"], telegram_id)
            active = member.status in {"member","administrator","creator"} or (member.status == "restricted" and member.is_member)
            await self._users.save_referral_profile({**profile,"holder_active":active,"holder_verified_at":datetime.now(UTC).isoformat()})
        return await self._users.referral_stats(telegram_id)

    async def request_withdrawal(self, uid: int, currency: str, wallet: str) -> int:
        wallet=wallet.strip()
        if not re.fullmatch(r"(?:0|-1):[a-fA-F0-9]{64}",wallet):
            if not re.fullmatch(r"[A-Za-z0-9_+/\-]{48}",wallet):
                raise ValueError("Invalid TON address")
            raw=base64.urlsafe_b64decode(wallet)
            if len(raw)!=36 or raw[0] not in (0x11,0x51) or raw[1] not in (0,255) or binascii.crc_hqx(raw[:34],0)!=int.from_bytes(raw[34:],"big"):
                raise ValueError("Mainnet TON address with valid checksum required")
        return await self._users.request_referral_withdrawal(uid,currency,normalize_ton_address(wallet))

    async def withdrawals(self, uid: int | None = None) -> list[dict]:
        return await self._users.referral_withdrawals(uid)

    async def advance(self, row_id: int, status: str, tx_hash: str | None) -> None:
        await self._users.advance_referral_withdrawal(row_id,status,tx_hash)

    async def set_profile(self, uid: int, level: str, chat_id: int | None) -> None:
        if level not in {"special","holder","normal"} or (level=="holder" and chat_id is None):
            raise ValueError("Use special, holder <chat_id>, or normal")
        await self._users.save_referral_profile({"user_id":uid,"special":level=="special","holder_chat_id":chat_id if level=="holder" else None,"holder_active":False,"holder_verified_at":None})

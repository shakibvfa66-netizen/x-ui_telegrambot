from __future__ import annotations

from decimal import Decimal, ROUND_UP


def format_toman(amount: int) -> str:
    return f"{amount:,} تومان"


def format_bytes_as_gb(data_gb: int) -> str:
    return f"{data_gb:,} گیگابایت"


def estimate_usdt(price_toman: int, toman_per_usdt: int) -> str:
    if toman_per_usdt <= 0:
        return "نامشخص"
    amount = Decimal(price_toman) / Decimal(toman_per_usdt)
    return str(amount.quantize(Decimal("0.01"), rounding=ROUND_UP))

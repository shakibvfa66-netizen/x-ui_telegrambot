from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Plan:
    code: str
    title: str
    price_toman: int
    data_gb: int
    duration_days: int
    inbound_id: int


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: set[int]
    support_username: str
    database_path: Path
    panel_base_url: str
    panel_public_base_url: str
    panel_username: str
    panel_password: str
    panel_dry_run: bool
    panel_sub_path_template: str
    default_inbound_id: int
    card_number: str
    card_holder: str
    crypto_wallets: dict[str, str]
    usdt_toman_rate: int
    plans: list[Plan]

    @property
    def plans_by_code(self) -> dict[str, Plan]:
        return {plan.code: plan for plan in self.plans}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    return int(value.strip())


def _parse_admin_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    ids: set[int] = set()
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if item:
            ids.add(int(item))
    return ids


def _parse_json_dict(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("CRYPTO_WALLETS_JSON باید یک آبجکت JSON باشد.")
    return {str(key): str(value) for key, value in parsed.items()}


def _default_plans(default_inbound_id: int) -> list[Plan]:
    return [
        Plan("basic", "پلن اقتصادی 30 گیگ / 30 روز", 120_000, 30, 30, default_inbound_id),
        Plan("standard", "پلن استاندارد 60 گیگ / 30 روز", 210_000, 60, 30, default_inbound_id),
        Plan("pro", "پلن حرفه‌ای 120 گیگ / 30 روز", 380_000, 120, 30, default_inbound_id),
    ]


def _parse_plans(raw: str | None, default_inbound_id: int) -> list[Plan]:
    if not raw:
        return _default_plans(default_inbound_id)
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("PLANS_JSON باید یک لیست JSON باشد.")

    plans: list[Plan] = []
    for item in data:
        plans.append(
            Plan(
                code=str(item["code"]),
                title=str(item["title"]),
                price_toman=int(item["price_toman"]),
                data_gb=int(item["data_gb"]),
                duration_days=int(item["duration_days"]),
                inbound_id=int(item.get("inbound_id") or default_inbound_id),
            )
        )
    return plans


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env")

    default_inbound_id = _int_env("DEFAULT_INBOUND_ID", 1)
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token or "CHANGE_ME" in bot_token:
        raise RuntimeError("BOT_TOKEN را در فایل .env تنظیم کن.")

    database_path = Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3"))
    if not database_path.is_absolute():
        database_path = project_root / database_path

    return Settings(
        bot_token=bot_token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS")),
        support_username=os.getenv("SUPPORT_USERNAME", "@support").strip(),
        database_path=database_path,
        panel_base_url=os.getenv("PANEL_BASE_URL", "").strip().rstrip("/"),
        panel_public_base_url=os.getenv("PANEL_PUBLIC_BASE_URL", "").strip().rstrip("/"),
        panel_username=os.getenv("PANEL_USERNAME", "").strip(),
        panel_password=os.getenv("PANEL_PASSWORD", "").strip(),
        panel_dry_run=_bool_env("PANEL_DRY_RUN", True),
        panel_sub_path_template=os.getenv("PANEL_SUB_PATH_TEMPLATE", "/sub/{sub_id}").strip(),
        default_inbound_id=default_inbound_id,
        card_number=os.getenv("CARD_NUMBER", "").strip(),
        card_holder=os.getenv("CARD_HOLDER", "").strip(),
        crypto_wallets=_parse_json_dict(os.getenv("CRYPTO_WALLETS_JSON")),
        usdt_toman_rate=_int_env("USDT_TOMAN_RATE", 65_000),
        plans=_parse_plans(os.getenv("PLANS_JSON"), default_inbound_id),
    )

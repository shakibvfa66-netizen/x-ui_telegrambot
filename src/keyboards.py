from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from .config import Plan
from .payments import format_toman


BTN_BUY = "خرید سرویس"
BTN_MY_SERVICES = "سرویس‌های من"
BTN_MY_PAYMENTS = "پرداخت‌های من"
BTN_HELP = "راهنما"
BTN_AGENT_ORDER = "ثبت سفارش مشتری"
BTN_PENDING_PAYMENTS = "درخواست‌های پرداخت"
BTN_ADD_AGENT = "افزودن همکار"
BTN_LIST_AGENTS = "لیست همکاران"


def main_menu(role: str) -> ReplyKeyboardMarkup:
    if role == "admin":
        rows = [
            [KeyboardButton(text=BTN_PENDING_PAYMENTS), KeyboardButton(text=BTN_ADD_AGENT)],
            [KeyboardButton(text=BTN_LIST_AGENTS), KeyboardButton(text=BTN_MY_SERVICES)],
            [KeyboardButton(text=BTN_HELP)],
        ]
    elif role == "agent":
        rows = [
            [KeyboardButton(text=BTN_AGENT_ORDER)],
            [KeyboardButton(text=BTN_MY_SERVICES), KeyboardButton(text=BTN_MY_PAYMENTS)],
            [KeyboardButton(text=BTN_HELP)],
        ]
    else:
        rows = [
            [KeyboardButton(text=BTN_BUY)],
            [KeyboardButton(text=BTN_MY_SERVICES), KeyboardButton(text=BTN_MY_PAYMENTS)],
            [KeyboardButton(text=BTN_HELP)],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, input_field_placeholder="یک گزینه را انتخاب کن")


def plans_keyboard(plans: list[Plan], prefix: str = "buy") -> InlineKeyboardMarkup:
    buttons = []
    for plan in plans:
        label = f"{plan.title} - {format_toman(plan.price_toman)}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"{prefix}:{plan.code}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_methods_keyboard(plan_code: str, prefix: str = "pay") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="کارت‌به‌کارت", callback_data=f"{prefix}:{plan_code}:card")],
            [InlineKeyboardButton(text="ارزدیجیتال", callback_data=f"{prefix}:{plan_code}:crypto")],
        ]
    )


def crypto_wallets_keyboard(wallets: dict[str, str]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=asset, callback_data=f"crypto_asset:{asset}")]
            for asset in wallets
        ]
    )


def admin_payment_actions(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="تایید و ساخت سرویس", callback_data=f"adminpay:approve:{payment_id}"),
                InlineKeyboardButton(text="رد پرداخت", callback_data=f"adminpay:reject:{payment_id}"),
            ]
        ]
    )

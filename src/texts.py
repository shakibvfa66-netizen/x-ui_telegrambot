from __future__ import annotations

from datetime import datetime

from .config import Plan
from .payments import format_toman


STATUS_LABELS = {
    "draft": "در انتظار ارسال رسید",
    "pending": "در صف تایید",
    "approved": "تایید شده",
    "rejected": "رد شده",
    "processing": "در حال ساخت سرویس",
}


METHOD_LABELS = {
    "card": "کارت‌به‌کارت",
    "crypto": "ارزدیجیتال",
    "agent_settlement": "تسویه همکار",
}


def plan_line(plan: Plan) -> str:
    return (
        f"{plan.title}\n"
        f"حجم: {plan.data_gb} گیگ\n"
        f"مدت: {plan.duration_days} روز\n"
        f"قیمت: {format_toman(plan.price_toman)}"
    )


def payment_admin_text(payment: dict, plan: Plan) -> str:
    method = METHOD_LABELS.get(payment["method"], payment["method"])
    status = STATUS_LABELS.get(payment["status"], payment["status"])
    lines = [
        "درخواست پرداخت جدید",
        "",
        f"شماره درخواست: {payment['id']}",
        f"کاربر سرویس: {payment['user_tg_id']}",
        f"ثبت‌کننده: {payment['requested_by_tg_id']}",
        f"پلن: {plan.title}",
        f"مبلغ: {format_toman(payment['amount_toman'])}",
        f"روش: {method}",
        f"وضعیت: {status}",
    ]
    if payment.get("crypto_asset"):
        lines.append(f"شبکه/ارز: {payment['crypto_asset']}")
    if payment.get("crypto_amount"):
        lines.append(f"مبلغ کریپتو: {payment['crypto_amount']}")
    if payment.get("proof_type") == "text" and payment.get("proof_value"):
        lines.extend(["", f"رسید/TXID: {payment['proof_value']}"])
    return "\n".join(lines)


def payment_user_text(payment: dict, plan: Plan) -> str:
    method = METHOD_LABELS.get(payment["method"], payment["method"])
    status = STATUS_LABELS.get(payment["status"], payment["status"])
    return (
        f"درخواست #{payment['id']}\n"
        f"پلن: {plan.title}\n"
        f"مبلغ: {format_toman(payment['amount_toman'])}\n"
        f"روش پرداخت: {method}\n"
        f"وضعیت: {status}"
    )


def service_text(service: dict, plan: Plan | None = None) -> str:
    expires = datetime.fromtimestamp(service["expires_at_ms"] / 1000).strftime("%Y-%m-%d")
    plan_title = plan.title if plan else service["plan_code"]
    return (
        f"سرویس #{service['id']}\n"
        f"پلن: {plan_title}\n"
        f"حجم: {service['total_gb']} گیگ\n"
        f"تاریخ پایان: {expires}\n"
        f"لینک سابسکریپشن:\n{service['subscription_url']}"
    )

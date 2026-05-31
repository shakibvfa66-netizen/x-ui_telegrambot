from __future__ import annotations

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .config import Plan, Settings
from .db import Database
from .keyboards import (
    BTN_ADD_AGENT,
    BTN_AGENT_ORDER,
    BTN_BUY,
    BTN_HELP,
    BTN_LIST_AGENTS,
    BTN_MY_PAYMENTS,
    BTN_MY_SERVICES,
    BTN_PENDING_PAYMENTS,
    admin_payment_actions,
    crypto_wallets_keyboard,
    main_menu,
    payment_methods_keyboard,
    plans_keyboard,
)
from .payments import estimate_usdt, format_toman
from .sanaei_api import SanaeiAPI
from .texts import payment_admin_text, payment_user_text, plan_line, service_text


class PaymentStates(StatesGroup):
    waiting_card_proof = State()
    waiting_crypto_proof = State()


class AdminStates(StatesGroup):
    waiting_agent_id = State()


class AgentStates(StatesGroup):
    waiting_customer_id = State()


def register_handlers(dp: Dispatcher, db: Database, settings: Settings, panel: SanaeiAPI) -> None:
    router = Router()
    plans_by_code = settings.plans_by_code

    async def remember_user(message: Message) -> None:
        if not message.from_user:
            return
        user = message.from_user
        await db.upsert_user(user.id, user.username, user.full_name)

    async def role_for(message: Message | CallbackQuery) -> str:
        from_user = message.from_user
        if not from_user:
            return "user"
        return await db.role_of(from_user.id, settings.admin_ids)

    def get_plan(code: str) -> Plan | None:
        return plans_by_code.get(code)

    async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> None:
        try:
            await bot.send_message(chat_id, text, **kwargs)
        except Exception:
            pass

    async def send_payment_to_chat(bot: Bot, chat_id: int, payment: dict) -> None:
        plan = get_plan(payment["plan_code"])
        if not plan:
            await bot.send_message(chat_id, f"پلن این پرداخت پیدا نشد: {payment['plan_code']}")
            return
        text = payment_admin_text(payment, plan)
        markup = admin_payment_actions(payment["id"])
        proof_type = payment.get("proof_type")
        proof_value = payment.get("proof_value")
        try:
            if proof_type == "photo" and proof_value:
                await bot.send_photo(chat_id, proof_value, caption=text, reply_markup=markup)
            elif proof_type == "document" and proof_value:
                await bot.send_document(chat_id, proof_value, caption=text, reply_markup=markup)
            else:
                await bot.send_message(chat_id, text, reply_markup=markup)
        except Exception:
            await bot.send_message(chat_id, text, reply_markup=markup)

    async def notify_admins(bot: Bot, payment: dict) -> None:
        for admin_id in settings.admin_ids:
            await send_payment_to_chat(bot, admin_id, payment)

    def proof_from_message(message: Message) -> tuple[str, str] | None:
        if message.photo:
            return "photo", message.photo[-1].file_id
        if message.document:
            return "document", message.document.file_id
        if message.text and message.text.strip():
            return "text", message.text.strip()
        return None

    async def ask_for_card_proof(
        callback: CallbackQuery,
        state: FSMContext,
        *,
        plan: Plan,
        target_user_id: int,
        requested_by_tg_id: int,
    ) -> None:
        payment_id = await db.create_payment(
            user_tg_id=target_user_id,
            requested_by_tg_id=requested_by_tg_id,
            plan_code=plan.code,
            amount_toman=plan.price_toman,
            method="card",
        )
        await state.set_state(PaymentStates.waiting_card_proof)
        await state.update_data(payment_id=payment_id)
        await callback.message.answer(
            "پرداخت کارت‌به‌کارت\n\n"
            f"پلن: {plan.title}\n"
            f"مبلغ: {format_toman(plan.price_toman)}\n"
            f"شماره کارت: {settings.card_number or 'در .env تنظیم نشده'}\n"
            f"به نام: {settings.card_holder or 'در .env تنظیم نشده'}\n\n"
            "بعد از پرداخت، عکس رسید یا کد پیگیری را همین‌جا بفرست."
        )

    async def ask_for_crypto_asset(
        callback: CallbackQuery,
        state: FSMContext,
        *,
        plan: Plan,
        target_user_id: int,
        requested_by_tg_id: int,
    ) -> None:
        if not settings.crypto_wallets:
            await callback.message.answer("کیف پول ارزدیجیتال هنوز در تنظیمات ثبت نشده است.")
            return
        await state.update_data(
            target_user_id=target_user_id,
            requested_by_tg_id=requested_by_tg_id,
            plan_code=plan.code,
        )
        await callback.message.answer(
            "شبکه پرداخت ارزدیجیتال را انتخاب کن:",
            reply_markup=crypto_wallets_keyboard(settings.crypto_wallets),
        )

    async def create_settlement_request(
        callback: CallbackQuery,
        state: FSMContext,
        *,
        plan: Plan,
        target_user_id: int,
        requested_by_tg_id: int,
        bot: Bot,
    ) -> None:
        payment_id = await db.create_payment(
            user_tg_id=target_user_id,
            requested_by_tg_id=requested_by_tg_id,
            plan_code=plan.code,
            amount_toman=plan.price_toman,
            method="agent_settlement",
            status="pending",
        )
        payment = await db.get_payment(payment_id)
        await state.clear()
        if payment:
            await notify_admins(bot, payment)
        await callback.message.answer(
            "سفارش مشتری ثبت شد و برای تایید ادمین رفت.\n"
            f"شماره درخواست: {payment_id}",
            reply_markup=main_menu(await db.role_of(requested_by_tg_id, settings.admin_ids)),
        )

    async def handle_payment_method(callback: CallbackQuery, state: FSMContext, plan_code: str, method: str, bot: Bot) -> None:
        plan = get_plan(plan_code)
        if not plan:
            await callback.answer("این پلن پیدا نشد.", show_alert=True)
            return
        data = await state.get_data()
        target_user_id = int(data.get("target_user_id") or callback.from_user.id)
        requested_by_tg_id = int(data.get("requested_by_tg_id") or callback.from_user.id)
        if method == "card":
            await ask_for_card_proof(callback, state, plan=plan, target_user_id=target_user_id, requested_by_tg_id=requested_by_tg_id)
        elif method == "crypto":
            await ask_for_crypto_asset(callback, state, plan=plan, target_user_id=target_user_id, requested_by_tg_id=requested_by_tg_id)
        elif method == "settlement":
            await create_settlement_request(
                callback,
                state,
                plan=plan,
                target_user_id=target_user_id,
                requested_by_tg_id=requested_by_tg_id,
                bot=bot,
            )
        else:
            await callback.answer("روش پرداخت نامعتبر است.", show_alert=True)
            return
        await callback.answer()

    @router.message(CommandStart())
    async def start(message: Message, state: FSMContext) -> None:
        await state.clear()
        await remember_user(message)
        role = await role_for(message)
        await message.answer(
            "سلام، خوش آمدی.\n"
            "از منوی پایین گزینه مورد نظرت را انتخاب کن.",
            reply_markup=main_menu(role),
        )

    @router.message(Command("menu"))
    async def menu(message: Message, state: FSMContext) -> None:
        await state.clear()
        await remember_user(message)
        await message.answer("منوی اصلی:", reply_markup=main_menu(await role_for(message)))

    @router.message(Command("cancel"))
    async def cancel(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("عملیات لغو شد.", reply_markup=main_menu(await role_for(message)))

    @router.message(Command("id"))
    async def show_id(message: Message) -> None:
        if message.from_user:
            await message.answer(f"شناسه عددی تلگرام شما:\n{message.from_user.id}")

    @router.message(AdminStates.waiting_agent_id)
    async def receive_agent_id(message: Message, state: FSMContext) -> None:
        await remember_user(message)
        if await role_for(message) != "admin":
            await state.clear()
            await message.answer("این بخش فقط برای ادمین است.")
            return
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer("لطفاً فقط شناسه عددی تلگرام همکار را بفرست.")
            return
        tg_id = int(text)
        await db.add_agent(tg_id)
        await state.clear()
        await message.answer(f"همکار با شناسه {tg_id} اضافه شد.", reply_markup=main_menu("admin"))

    @router.message(AgentStates.waiting_customer_id)
    async def receive_customer_id(message: Message, state: FSMContext) -> None:
        await remember_user(message)
        role = await role_for(message)
        if role not in {"agent", "admin"}:
            await state.clear()
            await message.answer("این بخش برای همکارهاست.")
            return
        text = (message.text or "").strip()
        if not text.isdigit():
            await message.answer("شناسه عددی تلگرام مشتری را وارد کن. مثال: 123456789")
            return
        customer_id = int(text)
        await db.ensure_user(customer_id)
        await state.update_data(target_user_id=customer_id, requested_by_tg_id=message.from_user.id)
        await message.answer(
            f"مشتری: {customer_id}\nپلن را انتخاب کن:",
            reply_markup=plans_keyboard(settings.plans, prefix="agent_plan"),
        )

    @router.message(PaymentStates.waiting_card_proof)
    async def receive_card_proof(message: Message, state: FSMContext, bot: Bot) -> None:
        proof = proof_from_message(message)
        if not proof:
            await message.answer("لطفاً عکس رسید، فایل رسید، یا کد پیگیری را بفرست.")
            return
        data = await state.get_data()
        payment_id = int(data["payment_id"])
        await db.attach_payment_proof(payment_id, proof[0], proof[1])
        payment = await db.get_payment(payment_id)
        await state.clear()
        if payment:
            await notify_admins(bot, payment)
        await message.answer(
            "رسید ثبت شد و برای ادمین رفت.\n"
            "بعد از تایید، سرویس ساخته می‌شود.",
            reply_markup=main_menu(await role_for(message)),
        )

    @router.message(PaymentStates.waiting_crypto_proof)
    async def receive_crypto_proof(message: Message, state: FSMContext, bot: Bot) -> None:
        proof = proof_from_message(message)
        if not proof:
            await message.answer("لطفاً TXID، عکس رسید، یا فایل رسید را بفرست.")
            return
        data = await state.get_data()
        payment_id = int(data["payment_id"])
        await db.attach_payment_proof(payment_id, proof[0], proof[1])
        payment = await db.get_payment(payment_id)
        await state.clear()
        if payment:
            await notify_admins(bot, payment)
        await message.answer(
            "اطلاعات تراکنش ثبت شد و برای ادمین رفت.\n"
            "بعد از تایید، سرویس ساخته می‌شود.",
            reply_markup=main_menu(await role_for(message)),
        )

    @router.message(F.text == BTN_BUY)
    async def buy(message: Message, state: FSMContext) -> None:
        await remember_user(message)
        await state.update_data(target_user_id=message.from_user.id, requested_by_tg_id=message.from_user.id)
        await message.answer("پلن مورد نظر را انتخاب کن:", reply_markup=plans_keyboard(settings.plans, prefix="buy"))

    @router.message(F.text == BTN_AGENT_ORDER)
    async def agent_order(message: Message, state: FSMContext) -> None:
        await remember_user(message)
        role = await role_for(message)
        if role not in {"agent", "admin"}:
            await message.answer("این گزینه برای همکارهاست.")
            return
        await state.set_state(AgentStates.waiting_customer_id)
        await message.answer(
            "شناسه عددی تلگرام مشتری را بفرست.\n"
            "اگر مشتری شناسه‌اش را نمی‌داند، می‌تواند در بات دستور /id را بزند."
        )

    @router.message(F.text == BTN_MY_SERVICES)
    async def my_services(message: Message) -> None:
        await remember_user(message)
        services = await db.list_services(message.from_user.id)
        if not services:
            await message.answer("فعلاً سرویسی ثبت نشده است.")
            return
        for service in services:
            await message.answer(service_text(service, get_plan(service["plan_code"])))

    @router.message(F.text == BTN_MY_PAYMENTS)
    async def my_payments(message: Message) -> None:
        await remember_user(message)
        payments = await db.list_user_payments(message.from_user.id)
        if not payments:
            await message.answer("فعلاً پرداختی ثبت نشده است.")
            return
        for payment in payments:
            plan = get_plan(payment["plan_code"])
            if plan:
                await message.answer(payment_user_text(payment, plan))

    @router.message(F.text == BTN_HELP)
    async def help_text(message: Message) -> None:
        await remember_user(message)
        await message.answer(
            "راهنما\n\n"
            "برای خرید سرویس، از منوی اصلی «خرید سرویس» را بزن.\n"
            "بعد از ارسال رسید، ادمین پرداخت را بررسی می‌کند و لینک سابسکریپشن برایت ارسال می‌شود.\n\n"
            f"پشتیبانی: {settings.support_username}"
        )

    @router.message(F.text == BTN_PENDING_PAYMENTS)
    async def pending_payments(message: Message, bot: Bot) -> None:
        await remember_user(message)
        if await role_for(message) != "admin":
            await message.answer("این بخش فقط برای ادمین است.")
            return
        payments = await db.list_pending_payments()
        if not payments:
            await message.answer("درخواست در انتظار تاییدی وجود ندارد.")
            return
        for payment in payments:
            await send_payment_to_chat(bot, message.chat.id, payment)

    @router.message(F.text == BTN_ADD_AGENT)
    async def add_agent(message: Message, state: FSMContext) -> None:
        await remember_user(message)
        if await role_for(message) != "admin":
            await message.answer("این بخش فقط برای ادمین است.")
            return
        await state.set_state(AdminStates.waiting_agent_id)
        await message.answer("شناسه عددی تلگرام همکار را بفرست.")

    @router.message(F.text == BTN_LIST_AGENTS)
    async def list_agents(message: Message) -> None:
        await remember_user(message)
        if await role_for(message) != "admin":
            await message.answer("این بخش فقط برای ادمین است.")
            return
        agents = await db.list_agents()
        if not agents:
            await message.answer("هنوز همکاری ثبت نشده است.")
            return
        lines = ["لیست همکاران:"]
        for agent in agents:
            label = agent.get("label") or agent.get("full_name") or "-"
            username = f"@{agent['username']}" if agent.get("username") else "-"
            status = "فعال" if int(agent["active"]) == 1 else "غیرفعال"
            lines.append(f"{agent['tg_id']} | {username} | {label} | {status}")
        await message.answer("\n".join(lines))

    @router.callback_query(F.data.startswith("buy:"))
    async def choose_plan(callback: CallbackQuery, state: FSMContext) -> None:
        plan_code = callback.data.split(":", 1)[1]
        plan = get_plan(plan_code)
        if not plan:
            await callback.answer("این پلن پیدا نشد.", show_alert=True)
            return
        await state.update_data(target_user_id=callback.from_user.id, requested_by_tg_id=callback.from_user.id)
        await callback.message.answer(plan_line(plan), reply_markup=payment_methods_keyboard(plan.code, prefix="pay"))
        await callback.answer()

    @router.callback_query(F.data.startswith("agent_plan:"))
    async def agent_choose_plan(callback: CallbackQuery, state: FSMContext) -> None:
        role = await role_for(callback)
        if role not in {"agent", "admin"}:
            await callback.answer("این بخش برای همکارهاست.", show_alert=True)
            return
        plan_code = callback.data.split(":", 1)[1]
        plan = get_plan(plan_code)
        if not plan:
            await callback.answer("این پلن پیدا نشد.", show_alert=True)
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="کارت‌به‌کارت مشتری", callback_data=f"agent_pay:{plan.code}:card")],
                [InlineKeyboardButton(text="ارزدیجیتال مشتری", callback_data=f"agent_pay:{plan.code}:crypto")],
                [InlineKeyboardButton(text="تسویه با ادمین", callback_data=f"agent_pay:{plan.code}:settlement")],
            ]
        )
        await callback.message.answer(plan_line(plan), reply_markup=keyboard)
        await callback.answer()

    @router.callback_query(F.data.startswith("pay:"))
    async def payment_method(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        _, plan_code, method = callback.data.split(":", 2)
        await handle_payment_method(callback, state, plan_code, method, bot)

    @router.callback_query(F.data.startswith("agent_pay:"))
    async def agent_payment_method(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
        _, plan_code, method = callback.data.split(":", 2)
        await handle_payment_method(callback, state, plan_code, method, bot)

    @router.callback_query(F.data.startswith("crypto_asset:"))
    async def crypto_asset(callback: CallbackQuery, state: FSMContext) -> None:
        asset = callback.data.split(":", 1)[1]
        data = await state.get_data()
        plan = get_plan(str(data.get("plan_code") or ""))
        if not plan:
            await callback.answer("پلن پرداخت پیدا نشد. دوباره شروع کن.", show_alert=True)
            return
        wallet = settings.crypto_wallets.get(asset)
        if not wallet:
            await callback.answer("کیف پول این شبکه پیدا نشد.", show_alert=True)
            return
        target_user_id = int(data.get("target_user_id") or callback.from_user.id)
        requested_by_tg_id = int(data.get("requested_by_tg_id") or callback.from_user.id)
        crypto_amount = estimate_usdt(plan.price_toman, settings.usdt_toman_rate) if "USDT" in asset.upper() else None
        payment_id = await db.create_payment(
            user_tg_id=target_user_id,
            requested_by_tg_id=requested_by_tg_id,
            plan_code=plan.code,
            amount_toman=plan.price_toman,
            method="crypto",
            crypto_asset=asset,
            crypto_amount=crypto_amount,
        )
        await state.set_state(PaymentStates.waiting_crypto_proof)
        await state.update_data(payment_id=payment_id)
        amount_line = f"\nمبلغ تقریبی: {crypto_amount} USDT" if crypto_amount else ""
        await callback.message.answer(
            "پرداخت ارزدیجیتال\n\n"
            f"پلن: {plan.title}\n"
            f"مبلغ تومانی: {format_toman(plan.price_toman)}"
            f"{amount_line}\n"
            f"شبکه/ارز: {asset}\n"
            f"آدرس کیف پول:\n{wallet}\n\n"
            "بعد از پرداخت، TXID یا اسکرین‌شات رسید را همین‌جا بفرست."
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("adminpay:"))
    async def admin_payment_action(callback: CallbackQuery, bot: Bot) -> None:
        if await role_for(callback) != "admin":
            await callback.answer("این بخش فقط برای ادمین است.", show_alert=True)
            return
        _, action, raw_payment_id = callback.data.split(":", 2)
        payment_id = int(raw_payment_id)
        payment = await db.get_payment(payment_id)
        if not payment:
            await callback.answer("پرداخت پیدا نشد.", show_alert=True)
            return
        if payment["status"] != "pending":
            await callback.answer("این پرداخت قبلاً بررسی شده است.", show_alert=True)
            return
        plan = get_plan(payment["plan_code"])
        if not plan:
            await callback.answer("پلن پرداخت پیدا نشد.", show_alert=True)
            return

        if action == "reject":
            await db.set_payment_status(payment_id, "rejected")
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(f"پرداخت #{payment_id} رد شد.")
            await safe_send(bot, payment["user_tg_id"], f"پرداخت #{payment_id} رد شد. برای پیگیری با پشتیبانی در ارتباط باش.")
            if payment["requested_by_tg_id"] != payment["user_tg_id"]:
                await safe_send(bot, payment["requested_by_tg_id"], f"پرداخت مشتری برای درخواست #{payment_id} رد شد.")
            await callback.answer()
            return

        if action != "approve":
            await callback.answer("عملیات نامعتبر است.", show_alert=True)
            return

        await db.set_payment_status(payment_id, "processing")
        try:
            created = await panel.create_client(plan, payment["user_tg_id"], payment_id)
            service_id = await db.create_service(
                user_tg_id=payment["user_tg_id"],
                created_by_tg_id=payment["requested_by_tg_id"],
                payment_id=payment_id,
                plan_code=plan.code,
                client_uuid=created.client_uuid,
                client_email=created.email,
                sub_id=created.sub_id,
                subscription_url=created.subscription_url,
                total_gb=created.total_gb,
                expires_at_ms=created.expires_at_ms,
            )
            await db.set_payment_status(payment_id, "approved")
        except Exception as exc:
            await db.set_payment_status(payment_id, "pending", str(exc))
            await callback.message.answer(
                f"پرداخت تایید نشد چون ساخت سرویس در پنل ناموفق بود:\n{exc}"
            )
            await callback.answer("ساخت سرویس ناموفق بود.", show_alert=True)
            return

        await callback.message.edit_reply_markup(reply_markup=None)
        service = {
            "id": service_id,
            "plan_code": plan.code,
            "total_gb": created.total_gb,
            "expires_at_ms": created.expires_at_ms,
            "subscription_url": created.subscription_url,
        }
        user_message = (
            "پرداخت تایید شد و سرویس ساخته شد.\n\n"
            f"{service_text(service, plan)}"
        )
        await safe_send(bot, payment["user_tg_id"], user_message)
        if payment["requested_by_tg_id"] != payment["user_tg_id"]:
            await safe_send(
                bot,
                payment["requested_by_tg_id"],
                "سفارش مشتری تایید شد و سرویس ساخته شد.\n\n" + service_text(service, plan),
            )
        await callback.message.answer(f"سرویس #{service_id} برای پرداخت #{payment_id} ساخته شد.")
        await callback.answer("سرویس ساخته شد.")

    @router.message()
    async def fallback(message: Message) -> None:
        await remember_user(message)
        await message.answer(
            "متوجه نشدم. از منوی پایین گزینه مورد نظرت را انتخاب کن.",
            reply_markup=main_menu(await role_for(message)),
        )

    dp.include_router(router)

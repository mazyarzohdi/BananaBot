"""Automated order fulfillment service for payments (CardGozar & Auto Payments).

Handles immediate provisioning of VPN subscriptions, renewals, reseller plans,
or wallet credits upon confirmed payment.
"""

import asyncio
import logging
import time

from aiogram import Bot

from bot.keyboards import (
    complete_purchase_inline,
    main_menu,
    renew_complete_inline,
    reseller_complete_inline,
    service_actions_inline,
)
from bot.messages import t
from services.subscription import SubscriptionService

logger = logging.getLogger(__name__)

_CLAIM_TIMESTAMPS: dict[int, float] = {}
_PAYMENT_LOCKS: dict[int, asyncio.Lock] = {}


def _get_payment_lock(payment_id: int) -> asyncio.Lock:
    if payment_id not in _PAYMENT_LOCKS:
        _PAYMENT_LOCKS[payment_id] = asyncio.Lock()
    return _PAYMENT_LOCKS[payment_id]


async def fulfill_payment(bot: Bot, db, payment_id: int, force: bool = False) -> dict:
    """Fulfills an approved payment: creates subscription, renews, or tops up balance.

    Args:
        bot: Aiogram Bot instance for sending notifications and config links.
        db: Database instance.
        payment_id: ID of the payment to fulfill.
        force: If True (e.g. from manual user verify button), breaks any stale locks.

    Returns:
        Dict describing fulfillment outcome: {"status": "fulfilled"|"credited"|"already_fulfilled"|"already_claimed"|"error", ...}
    """
    payment = await db.get_payment(payment_id)
    if not payment:
        logger.error("Payment #%s not found for fulfillment.", payment_id)
        return {"status": "error", "message": "payment_not_found"}

    # Idempotency check: if order_id is already set (> 0), already fulfilled
    existing_order_id = payment.get("order_id")
    if existing_order_id and existing_order_id > 0:
        logger.warning("Payment #%s is already fulfilled (order_id=%s). Skipping duplicate fulfillment.", payment_id, existing_order_id)
        return {"status": "already_fulfilled", "order_id": existing_order_id}

    now = time.time()
    last_claimed_at = _CLAIM_TIMESTAMPS.get(payment_id, 0.0)
    if (now - last_claimed_at < 20.0) and not force:
        logger.warning("Payment #%s is currently being fulfilled by another task (in-memory lock). Skipping.", payment_id)
        return {"status": "already_claimed"}

    async with _get_payment_lock(payment_id):
        # Refresh payment under lock
        payment = await db.get_payment(payment_id)
        if payment.get("order_id") and payment["order_id"] > 0:
            return {"status": "already_fulfilled", "order_id": payment["order_id"]}

        if force:
            # Reset any stuck lock when user manually verifies
            await db._execute("UPDATE payments SET handled_by = NULL WHERE id = ? AND handled_by IN (-1, -2)", (payment_id,))

        # Atomically lock/claim using handled_by (handled_by has no foreign key constraint)
        claimed = await db._execute(
            "UPDATE payments SET handled_by = -1 WHERE id = ? AND (handled_by IS NULL OR handled_by = 0)",
            (payment_id,)
        )
        if claimed == 0:
            if payment.get("handled_by") == -1 and (now - last_claimed_at >= 20.0 or force):
                logger.info("Reclaiming stale lock on payment #%s", payment_id)
                claimed = 1
            else:
                logger.warning("Payment #%s is currently being fulfilled by another task. Skipping.", payment_id)
                return {"status": "already_claimed"}

        _CLAIM_TIMESTAMPS[payment_id] = now
        try:
            return await _do_fulfill_payment(bot, db, payment_id, payment)
        except Exception as unhandled_err:
            logger.exception("Unhandled failure in fulfill_payment for #%s: %s", payment_id, unhandled_err)
            await db._execute("UPDATE payments SET handled_by = -2 WHERE id = ? AND handled_by = -1", (payment_id,))
            return {"status": "error", "message": str(unhandled_err)}
        finally:
            _CLAIM_TIMESTAMPS.pop(payment_id, None)


async def _do_fulfill_payment(bot: Bot, db, payment_id: int, payment: dict) -> dict:
    user = await db._fetchone("SELECT * FROM users WHERE id = ?", (payment["user_id"],))
    if not user:
        logger.error("User #%s not found for payment #%s.", payment["user_id"], payment_id)
        await db._execute("UPDATE payments SET handled_by = -2 WHERE id = ?", (payment_id,))
        return {"status": "error", "message": "user_not_found"}

    telegram_id = int(user["telegram_id"])
    sub_service = SubscriptionService()

    # 1. Product purchase fulfillment
    if payment.get("product_id"):
        product = await db.get_product(payment["product_id"])
        if not product:
            logger.warning("Product #%s not found for payment #%s. Kept as wallet deposit.", payment["product_id"], payment_id)
            await db._execute("UPDATE payments SET handled_by = 0 WHERE id = ?", (payment_id,))
            await _notify_deposit_success(bot, telegram_id, payment["amount"], user["balance"])
            return {"status": "credited", "type": "product_fallback"}

        try:
            # Provision client subscription on panel
            result = await sub_service.create_from_product(
                user_id=user["id"],
                telegram_id=telegram_id,
                product=product,
            )

            # Deduct balance (the payment amount was already credited upon approval)
            price = max(0, product["price"] - int(payment.get("discount_amount") or 0))
            await db.deduct_balance_atomic(user["id"], price)

            # Record order in orders table
            coupon_note = f" (کوپن: {payment['coupon_code']})" if payment.get("coupon_code") else ""
            gateway_note = f"از درگاه {payment.get('payment_method', 'cardgozar')}"
            order_id, _ = await db.create_order(
                user["id"],
                product["id"],
                price,
                payment.get("payment_method", "cardgozar"),
                f"خرید {product['name']} {gateway_note}{coupon_note}",
            )
            # Save valid order_id to payments table and clear handled_by
            await db._execute("UPDATE payments SET order_id = ?, handled_by = 0 WHERE id = ?", (order_id, payment_id))

            # Send delivery message to user
            msg = t(
                "purchase_success",
                email=result["email"],
                volume=product["volume_gb"],
                days=product["duration_days"],
            )
            if payment.get("coupon_code"):
                msg += f"\n\n🎟 کوپن «{payment['coupon_code']}» اعمال شد."

            if payment.get("gateway_ref_id"):
                msg += f"\n\n💳 کد رهگیری بانکی: `{payment['gateway_ref_id']}`"

            try:
                await bot.send_message(
                    telegram_id,
                    msg,
                    parse_mode="Markdown",
                    reply_markup=service_actions_inline(result["id"], show_back=False),
                )
            except Exception as send_err:
                logger.warning("Markdown send failed in fulfillment (%s), falling back to clean text", send_err)
                clean_msg = msg.replace("`", "").replace("<code>", "").replace("</code>", "")
                await bot.send_message(
                    telegram_id,
                    clean_msg,
                    reply_markup=service_actions_inline(result["id"], show_back=False),
                )
            logger.info("Automatically delivered product #%s for user %s (payment #%s, order #%s)", product["id"], telegram_id, payment_id, order_id)
            return {"status": "fulfilled", "type": "product", "sub_id": result["id"], "order_id": order_id}

        except Exception as exc:
            logger.exception("Failed to provision subscription on panel for payment #%s: %s", payment_id, exc)
            # Mark handled_by = -2 so background poller doesn't infinitely loop
            await db._execute("UPDATE payments SET handled_by = -2 WHERE id = ?", (payment_id,))
            # Safe fallback: Money is safely preserved in user's wallet!
            fail_msg = (
                f"✅ پرداخت شما به مبلغ {payment['amount']:,} تومان تایید و به موجودی کیف پول شما افزوده شد.\n\n"
                f"⚠️ به دلیل خطای موقت در اتصال به سرور، اکانت به‌صورت خودکار ایجاد نشد. "
                f"موجودی در کیف پول شما محفوظ است و می‌توانید با کلیک روی دکمه زیر ساخت سرویس را مجدداً تکمیل کنید 👇"
            )
            try:
                await bot.send_message(
                    telegram_id,
                    fail_msg,
                    reply_markup=complete_purchase_inline(product["id"]),
                )
            except Exception:
                pass
            return {"status": "credited", "type": "product_error", "error": str(exc)}

    # 2. Subscription renewal fulfillment
    elif payment.get("renew_sub_id"):
        sub = await db.get_subscription(payment["renew_sub_id"])
        if sub and sub.get("product_id"):
            product = await db.get_product(sub["product_id"])
            if product:
                try:
                    await sub_service.renew_subscription(
                        sub["id"],
                        product["duration_days"],
                        product["volume_gb"],
                    )
                    await db.deduct_balance_atomic(user["id"], product["price"])
                    order_id, _ = await db.create_order(
                        user["id"],
                        product["id"],
                        product["price"],
                        payment.get("payment_method", "cardgozar"),
                        f"تمدید سرویس #{sub['id']} از درگاه {payment.get('payment_method', 'cardgozar')}",
                    )
                    await db._execute("UPDATE payments SET order_id = ?, handled_by = 0 WHERE id = ?", (order_id, payment_id))
                    renew_msg = (
                        f"✅ سرویس #{sub['id']} ({sub['email']}) شما با موفقیت تمدید شد!\n"
                        f"📊 حجم جدید: {product['volume_gb']} GB\n"
                        f"⏱ زمان تمدید: {product['duration_days']} روز"
                    )
                    if payment.get("gateway_ref_id"):
                        renew_msg += f"\n💳 کد رهگیری بانکی: <code>{payment['gateway_ref_id']}</code>"

                    await bot.send_message(
                        telegram_id,
                        renew_msg,
                        parse_mode="HTML",
                        reply_markup=service_actions_inline(sub["id"], show_back=False),
                    )
                    logger.info("Automatically renewed subscription #%s for user %s (payment #%s, order #%s)", sub["id"], telegram_id, payment_id, order_id)
                    return {"status": "fulfilled", "type": "renew", "sub_id": sub["id"], "order_id": order_id}
                except Exception as exc:
                    logger.exception("Failed to auto-renew subscription #%s: %s", sub["id"], exc)
                    await db._execute("UPDATE payments SET handled_by = -2 WHERE id = ?", (payment_id,))
                    await bot.send_message(
                        telegram_id,
                        f"✅ پرداخت شما تایید و موجودی شما شارژ شد.\nجهت تکمیل تمدید سرویس روی دکمه زیر بزنید 👇",
                        reply_markup=renew_complete_inline(sub["id"]),
                    )
                    return {"status": "credited", "type": "renew_error", "error": str(exc)}

        # Fallback if sub not found
        await db._execute("UPDATE payments SET handled_by = 0 WHERE id = ?", (payment_id,))
        await _notify_deposit_success(bot, telegram_id, payment["amount"], user["balance"])
        return {"status": "credited", "type": "renew_fallback"}

    # 3. Reseller plan purchase fulfillment
    elif payment.get("reseller_plan_id"):
        plan = await db.get_reseller_plan(payment["reseller_plan_id"])
        if plan:
            try:
                now = int(time.time())
                duration_days = int(plan.get("duration_days", 0) or 0)
                expires_at = (now + duration_days * 86400) if duration_days > 0 else 0
                await db.create_or_renew_reseller(
                    user_id=user["id"],
                    plan_id=plan["id"],
                    panel_id=plan["panel_id"],
                    quota_gb=float(plan["volume_gb"]),
                    expires_at=expires_at,
                )
                await db.deduct_balance_atomic(user["id"], plan["price"])
                order_id, _ = await db.create_order(
                    user["id"],
                    None,
                    plan["price"],
                    payment.get("payment_method", "cardgozar"),
                    f"خرید/تمدید نمایندگی {plan['name']}",
                )
                await db._execute("UPDATE payments SET order_id = ?, handled_by = 0 WHERE id = ?", (order_id, payment_id))
                reseller_msg = (
                    f"✅ پلن نمایندگی «{plan['name']}» با موفقیت برای شما فعال شد!\n"
                    f"📊 سقف حجم: {plan['volume_gb']} GB\n"
                    f"⏱ مدت اعتبار: {plan['duration_days']} روز\n\n"
                    f"از طریق منوی «🤝 پنل نمایندگی» می‌توانید اقدام به ساخت و مدیریت کانفیگ‌ها نمایید."
                )
                if payment.get("gateway_ref_id"):
                    reseller_msg += f"\n\n💳 کد رهگیری بانکی: <code>{payment['gateway_ref_id']}</code>"

                await bot.send_message(telegram_id, reseller_msg, parse_mode="HTML", reply_markup=main_menu())
                logger.info("Automatically activated reseller plan #%s for user %s (payment #%s, order #%s)", plan["id"], telegram_id, payment_id, order_id)
                return {"status": "fulfilled", "type": "reseller", "plan_id": plan["id"], "order_id": order_id}
            except Exception as exc:
                logger.exception("Failed to auto-activate reseller plan #%s: %s", plan["id"], exc)
                await db._execute("UPDATE payments SET handled_by = -2 WHERE id = ?", (payment_id,))
                await bot.send_message(
                    telegram_id,
                    f"✅ پرداخت تایید شد. لطفاً برای تکمیل فعال‌سازی نمایندگی روی دکمه زیر بزنید 👇",
                    reply_markup=reseller_complete_inline(plan["id"]),
                )
                return {"status": "credited", "type": "reseller_error", "error": str(exc)}

        await db._execute("UPDATE payments SET handled_by = 0 WHERE id = ?", (payment_id,))
        await _notify_deposit_success(bot, telegram_id, payment["amount"], user["balance"])
        return {"status": "credited", "type": "reseller_fallback"}

    # 4. Standard wallet deposit fulfillment
    else:
        await db._execute("UPDATE payments SET handled_by = 0 WHERE id = ?", (payment_id,))
        fresh_user = await db._fetchone("SELECT balance FROM users WHERE id = ?", (user["id"],))
        balance = fresh_user["balance"] if fresh_user else user["balance"]
        await _notify_deposit_success(bot, telegram_id, payment["amount"], balance, payment.get("gateway_ref_id"))
        return {"status": "fulfilled", "type": "deposit"}


async def _notify_deposit_success(bot: Bot, telegram_id: int, amount: int, current_balance: int, ref_id: str | None = None):
    text = (
        f"✅ <b>پرداخت شما با موفقیت تایید شد!</b>\n\n"
        f"💰 مبلغ: <b>{amount:,} تومان</b> به کیف پول شما اضافه شد.\n"
        f"💵 موجودی فعلی: <b>{current_balance:,} تومان</b>"
    )
    if ref_id:
        text += f"\n💳 کد پیگیری بانکی: <code>{ref_id}</code>"
    text += "\n\nهم‌اکنون می‌توانید از طریق منوی اصلی اقدام به خرید یا تمدید سرویس نمایید."

    try:
        await bot.send_message(telegram_id, text, reply_markup=main_menu(), parse_mode="HTML")
    except Exception as exc:
        logger.warning("Could not send deposit success message to %s: %s", telegram_id, exc)

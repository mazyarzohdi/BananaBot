"""CardGozar (کارت‌گذر) P2P Payment Gateway Client.

Implements official REST API v1 for CardGozar (https://cardgozar.ir/dashboard/api-docs)
including payment creation, verification, public live polling, and HMAC-SHA256
webhook signature validation.
"""

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

try:
    import aiohttp
except ImportError:
    aiohttp = None

logger = logging.getLogger(__name__)


class CardGozarError(Exception):
    """Base exception for CardGozar API errors."""
    def __init__(self, message: str, status_code: int | None = None, response_data: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data or {}


class CardGozarClient:
    DEFAULT_BASE_URL = "https://cardgozar.ir"

    def __init__(self, api_key: str, secret_key: str = "", base_url: str = DEFAULT_BASE_URL):
        self.api_key = (api_key or "").strip()
        self.secret_key = (secret_key or "").strip()
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _headers(self, with_auth: bool = True) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BananaBot-CardGozar/1.0",
        }
        if with_auth and self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def create_payment(
        self,
        amount_rials: int | None = None,
        callback_url: str | None = None,
        order_id: str = "",
        description: str = "",
        timeout: int = 15,
        *,
        amount_toman: int | None = None,
    ) -> dict[str, Any]:
        """Creates a payment invoice on CardGozar.

        Args:
            amount_rials: Base amount in Rials (max 500,000,000 Rials).
            callback_url: Buyer return URL & webhook destination (optional).
            order_id: Merchant internal order/payment ID.
            description: Payment description displayed to the buyer.
            timeout: Request timeout in seconds.
            amount_toman: Base amount in Tomans (converted to Rials as amount_toman * 10).

        Returns:
            Dict containing order_token, tracking_code, payment_url, final_amount, etc.
        """
        if amount_rials is None:
            if amount_toman is not None:
                amount_rials = amount_toman * 10
            else:
                raise CardGozarError("مبلغ پرداخت مشخص نشده است.")

        if not self.api_key:
            raise CardGozarError("کلید API کارت‌گذر تنظیم نشده است.")

        if amount_rials <= 0:
            raise CardGozarError("مبلغ پرداخت باید بزرگ‌تر از صفر باشد.")

        url = f"{self.base_url}/api/v1/payments/create/"
        payload: dict[str, Any] = {
            "amount": int(amount_rials),
        }
        if callback_url:
            payload["callback_url"] = str(callback_url).strip()
        if order_id:
            payload["order_id"] = str(order_id)
        if description:
            payload["description"] = description[:500]

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._headers(with_auth=True),
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    status = resp.status
                    try:
                        data = await resp.json()
                    except Exception:
                        text = await resp.text()
                        data = {"error": text}

                    order_tok = data.get("order_token")
                    if status in (200, 201) and (data.get("payment_url") or order_tok):
                        if not data.get("payment_url") and order_tok:
                            data["payment_url"] = f"https://payments.cardgozar.ir/pay/{order_tok}"
                        logger.info(
                            "CardGozar order created: token=%s, final_amount=%s Rials",
                            data.get("order_token"),
                            data.get("final_amount"),
                        )
                        return data

                    err_msg = data.get("error") or data.get("detail") or data.get("message")
                    if status == 401:
                        err_msg = "کلید API کارت‌گذر نامعتبر است یا غیرفعال شده است."
                    elif status == 403:
                        err_msg = "درگاه کارت‌گذر به دلیل سقف بدهی معلق است. لطفاً کیف‌پول کارت‌گذر را شارژ کنید."
                    elif not err_msg:
                        err_msg = f"خطا در ایجاد سفارش درگاه کارت‌گذر (کد وضعیت: {status})"

                    raise CardGozarError(err_msg, status_code=status, response_data=data)

            except aiohttp.ClientError as exc:
                logger.error("Connection error to CardGozar create endpoint: %s", exc)
                raise CardGozarError(f"خطای ارتباط با سرور کارت‌گذر: {exc}") from exc

    async def verify_payment(self, order_token: str, timeout: int = 15) -> dict[str, Any]:
        """Queries and verifies payment completion with CardGozar API.

        Args:
            order_token: The order_token returned by create_payment.

        Returns:
            Dict containing is_paid (bool), ref_id, payer_card, amount, status, etc.
        """
        if not self.api_key:
            raise CardGozarError("کلید API کارت‌گذر تنظیم نشده است.")

        if not order_token:
            raise CardGozarError("شناسه سفارش (order_token) ارائه نشده است.")

        if not aiohttp:
            return self.verify_payment_sync(order_token, timeout)

        url = f"{self.base_url}/api/v1/payments/verify/{order_token}/"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    headers=self._headers(with_auth=True),
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    status = resp.status
                    try:
                        data = await resp.json()
                    except Exception:
                        text = await resp.text()
                        data = {"error": text}

                    if status == 200:
                        return data

                    err_msg = data.get("error") or data.get("detail") or f"خطا در استعلام تایید پرداخت ({status})"
                    raise CardGozarError(err_msg, status_code=status, response_data=data)

            except aiohttp.ClientError as exc:
                logger.error("Connection error to CardGozar verify endpoint: %s", exc)
                raise CardGozarError(f"خطای ارتباط در استعلام پرداخت: {exc}") from exc

    async def get_payment_status(self, order_token: str, timeout: int = 10) -> dict[str, Any]:
        """Queries live public status of an order without requiring API key.

        Returns:
            Dict containing is_paid, remaining_seconds, ref_id, etc.
        """
        if not order_token:
            raise CardGozarError("شناسه سفارش (order_token) ارائه نشده است.")

        if not aiohttp:
            return self.get_payment_status_sync(order_token, timeout)

        url = f"{self.base_url}/api/v1/payments/status/{order_token}/"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    headers=self._headers(with_auth=False),
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return {"is_paid": False, "status": "UNKNOWN"}
            except Exception as exc:
                logger.debug("Live status check error for %s: %s", order_token, exc)
                return {"is_paid": False, "error": str(exc)}

    def verify_payment_sync(self, order_token: str, timeout: float = 10) -> dict[str, Any]:
        """Queries and verifies payment completion with CardGozar API synchronously.
        Uses Python's standard library (urllib.request) without requiring aiohttp.
        """
        if not self.api_key:
            raise CardGozarError("کلید API کارت‌گذر تنظیم نشده است.")

        if not order_token:
            raise CardGozarError("شناسه سفارش (order_token) ارائه نشده است.")

        url = f"{self.base_url}/api/v1/payments/verify/{order_token}/"
        headers = self._headers(with_auth=True)
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                try:
                    data = json.loads(resp.read().decode("utf-8"))
                except Exception:
                    data = {}

                if status == 200:
                    return data

                err_msg = data.get("error") or data.get("detail") or f"خطا در استعلام تایید پرداخت ({status})"
                raise CardGozarError(err_msg, status_code=status, response_data=data)
        except urllib.error.HTTPError as exc:
            try:
                err_data = json.loads(exc.read().decode("utf-8"))
            except Exception:
                err_data = {}
            err_msg = err_data.get("error") or err_data.get("detail") or f"خطا در استعلام ({exc.code})"
            raise CardGozarError(err_msg, status_code=exc.code, response_data=err_data)
        except CardGozarError:
            raise
        except Exception as exc:
            logger.error("Sync connection error to CardGozar verify endpoint: %s", exc)
            raise CardGozarError(f"خطای ارتباط در استعلام پرداخت: {exc}") from exc

    def get_payment_status_sync(self, order_token: str, timeout: float = 10) -> dict[str, Any]:
        """Queries live public status of an order synchronously with urllib.request."""
        if not order_token:
            raise CardGozarError("شناسه سفارش (order_token) ارائه نشده است.")

        url = f"{self.base_url}/api/v1/payments/status/{order_token}/"
        headers = self._headers(with_auth=False)
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
                return {"is_paid": False, "status": "UNKNOWN"}
        except Exception as exc:
            logger.debug("Live sync status check error for %s: %s", order_token, exc)
            return {"is_paid": False, "error": str(exc)}

    def verify_webhook_signature(self, raw_body: bytes, signature_header: str) -> bool:
        """Verifies the HMAC-SHA256 signature sent with CardGozar webhook.

        Args:
            raw_body: Exact raw bytes of incoming POST request body.
            signature_header: Value of X-CardGozar-Signature header.

        Returns:
            True if valid, False otherwise.
        """
        if not self.secret_key:
            logger.warning("CardGozar secret_key is not configured; cannot verify signature.")
            return False

        if not signature_header:
            return False

        computed = hmac.new(
            self.secret_key.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed.lower(), signature_header.strip().lower())

    async def test_connection(self) -> tuple[bool, str]:
        """Tests whether the API key is recognized and connection works."""
        if not self.api_key:
            return False, "کلید API وارد نشده است."

        # Call verify with a dummy token to test authentication
        url = f"{self.base_url}/api/v1/payments/verify/test_connection_ping/"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    headers=self._headers(with_auth=True),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 401:
                        return False, "کلید API نامعتبر است (کد ۴۰۱ Unauthorized)."
                    if resp.status in (200, 400, 404):
                        # 404 or 400 means authentication passed and server recognized the merchant key!
                        return True, "ارتباط با موفقیت برقرار شد و کلید API معتبر است."
                    if resp.status == 403:
                        return False, "درگاه به دلیل سقف بدهی معلق است (کد ۴۰۳ Forbidden)."
                    return False, f"پاسخ غیرمنتظره از سرور: کد {resp.status}"
            except Exception as exc:
                return False, f"خطا در برقراری ارتباط با سرور: {exc}"

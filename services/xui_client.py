"""3x-ui (MHSanaei) panel API client."""

import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class XUIError(Exception):
    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


class XUIClient:
    """Async client for 3x-ui panel API using Bearer token authentication."""

    def __init__(self, base_url: str, api_token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
        }

    async def _request(
        self,
        method: str,
        path: str,
        data: dict | list | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            kwargs: dict[str, Any] = {"headers": self._headers()}
            if data is not None:
                kwargs["json"] = data
            async with session.request(method, url, **kwargs) as resp:
                text = await resp.text()
                try:
                    body = json.loads(text) if text else {}
                except json.JSONDecodeError:
                    body = {"raw": text}

                if resp.status >= 400:
                    msg = body.get("msg", body.get("message", f"HTTP {resp.status}"))
                    raise XUIError(str(msg), resp.status, body)

                if isinstance(body, dict) and body.get("success") is False:
                    raise XUIError(body.get("msg", "API error"), resp.status, body)

                return body

    async def get_server_status(self) -> dict:
        result = await self._request("GET", "/panel/api/server/status")
        return result.get("obj", result)

    async def list_inbounds(self) -> list[dict]:
        result = await self._request("GET", "/panel/api/inbounds/list")
        return result.get("obj", [])

    async def list_inbound_options(self) -> list[dict]:
        result = await self._request("GET", "/panel/api/inbounds/options")
        return result.get("obj", [])

    async def get_client(self, email: str) -> dict | None:
        result = await self._request("GET", f"/panel/api/clients/get/{email}")
        return result.get("obj")

    async def add_client(
        self,
        email: str,
        inbound_ids: list[int],
        total_gb: float,
        expiry_time_ms: int,
        sub_id: str | None = None,
        comment: str = "",
        tg_id: int = 0,
        on_hold: bool = False,
    ) -> dict:
        """Create a client on the panel.

        expiry_time_ms: Unix timestamp in milliseconds, or negative for on-hold days.
        total_gb: Traffic limit in GB (0 = unlimited).
        """
        total_bytes = int(total_gb * (1024 ** 3)) if total_gb > 0 else 0

        client_data: dict[str, Any] = {
            "email": email,
            "totalGB": total_bytes,
            "expiryTime": expiry_time_ms,
            "tgId": tg_id,
            "comment": comment,
            "enable": True,
        }
        if sub_id:
            client_data["subId"] = sub_id

        payload = {
            "inboundIds": inbound_ids,
            "client": client_data,
        }
        result = await self._request("POST", "/panel/api/clients/add", payload)
        return result.get("obj", result)

    async def update_client(self, email: str, client_data: dict) -> dict:
        result = await self._request(
            "POST", f"/panel/api/clients/update/{email}", client_data
        )
        return result.get("obj", result)

    async def delete_client(self, email: str, keep_traffic: bool = False) -> dict:
        path = f"/panel/api/clients/del/{email}"
        if keep_traffic:
            path += "?keepTraffic=1"
        result = await self._request("POST", path, {})
        return result.get("obj", result)

    async def reset_client_traffic(self, email: str) -> dict:
        result = await self._request(
            "POST", f"/panel/api/clients/resetTraffic/{email}", {}
        )
        return result.get("obj", result)

    async def get_client_traffic(self, email: str) -> dict:
        result = await self._request("GET", f"/panel/api/clients/traffic/{email}")
        return result.get("obj", {})

    async def get_client_links(self, email: str) -> list[str]:
        result = await self._request("GET", f"/panel/api/clients/links/{email}")
        obj = result.get("obj", [])
        if isinstance(obj, list):
            return obj
        if isinstance(obj, str):
            return [obj] if obj else []
        return []

    async def get_online_clients(self) -> list[str]:
        result = await self._request("POST", "/panel/api/clients/onlines", {})
        return result.get("obj", [])

    async def test_connection(self) -> bool:
        try:
            await self.get_server_status()
            return True
        except XUIError:
            return False


def compute_expiry_ms(
    duration_days: int,
    on_hold: bool = False,
    from_timestamp: int | None = None,
) -> int:
    """Compute expiryTime value for x-ui API."""
    import time

    if duration_days <= 0:
        return 0

    now = from_timestamp or int(time.time())
    expire_unix = now + duration_days * 86400

    if on_hold:
        # Negative milliseconds: days remaining for on-hold mode
        days_left = duration_days
        return -days_left * 86400000

    return expire_unix * 1000


def generate_client_email(telegram_id: int, suffix: str = "") -> str:
    import random
    import string
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    base = f"u{telegram_id}_{rand}"
    return f"{base}{suffix}" if suffix else base


def generate_sub_id() -> str:
    import random
    import string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=16))

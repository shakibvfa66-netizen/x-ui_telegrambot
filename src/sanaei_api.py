from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from .config import Plan, Settings


@dataclass(frozen=True)
class CreatedPanelClient:
    client_uuid: str
    email: str
    sub_id: str
    subscription_url: str
    total_gb: int
    expires_at_ms: int


class SanaeiAPI:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def create_client(self, plan: Plan, telegram_id: int, payment_id: int) -> CreatedPanelClient:
        client_uuid = str(uuid.uuid4())
        sub_id = secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16]
        email = f"tg{telegram_id}_{payment_id}"
        expires_at = datetime.now(timezone.utc) + timedelta(days=plan.duration_days)
        expires_at_ms = int(expires_at.timestamp() * 1000)

        result = CreatedPanelClient(
            client_uuid=client_uuid,
            email=email,
            sub_id=sub_id,
            subscription_url=self._subscription_url(sub_id),
            total_gb=plan.data_gb,
            expires_at_ms=expires_at_ms,
        )

        if self.settings.panel_dry_run:
            return result

        self._validate_panel_settings()
        base_url = self.settings.panel_base_url.rstrip("/") + "/"
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0, follow_redirects=True) as client:
            login_response = await client.post(
                "login",
                data={
                    "username": self.settings.panel_username,
                    "password": self.settings.panel_password,
                },
            )
            login_response.raise_for_status()
            self._raise_when_panel_failed(login_response)

            client_payload = {
                "id": client_uuid,
                "flow": "",
                "email": email,
                "limitIp": 0,
                "totalGB": plan.data_gb * 1024 * 1024 * 1024,
                "expiryTime": expires_at_ms,
                "enable": True,
                "tgId": str(telegram_id),
                "subId": sub_id,
                "comment": f"telegram payment #{payment_id}",
                "reset": 0,
            }
            response = await client.post(
                "panel/api/inbounds/addClient",
                json={
                    "id": plan.inbound_id,
                    "settings": json.dumps({"clients": [client_payload]}, ensure_ascii=False),
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            self._raise_when_panel_failed(response)
        return result

    def _subscription_url(self, sub_id: str) -> str:
        base = self.settings.panel_public_base_url or self.settings.panel_base_url
        if not base:
            base = "https://panel.example.com"
        path = self.settings.panel_sub_path_template.format(sub_id=quote(sub_id))
        if not path.startswith("/"):
            path = "/" + path
        return base.rstrip("/") + path

    def _validate_panel_settings(self) -> None:
        missing = []
        if not self.settings.panel_base_url:
            missing.append("PANEL_BASE_URL")
        if not self.settings.panel_username:
            missing.append("PANEL_USERNAME")
        if not self.settings.panel_password:
            missing.append("PANEL_PASSWORD")
        if missing:
            raise RuntimeError("این تنظیمات پنل کامل نیست: " + ", ".join(missing))

    @staticmethod
    def _raise_when_panel_failed(response: httpx.Response) -> None:
        if not response.content:
            return
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return
        data = response.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise RuntimeError(str(data.get("msg") or "پنل ساخت کلاینت را رد کرد."))

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys = ON")

    async def close(self) -> None:
        if self.conn:
            await self.conn.close()

    async def init(self) -> None:
        conn = self._conn()
        await conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS telegram_users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agents (
                tg_id INTEGER PRIMARY KEY,
                label TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS payment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_tg_id INTEGER NOT NULL,
                requested_by_tg_id INTEGER NOT NULL,
                plan_code TEXT NOT NULL,
                amount_toman INTEGER NOT NULL,
                method TEXT NOT NULL,
                crypto_asset TEXT,
                crypto_amount TEXT,
                proof_type TEXT,
                proof_value TEXT,
                status TEXT NOT NULL,
                admin_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_payment_status
                ON payment_requests(status, created_at);

            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_tg_id INTEGER NOT NULL,
                created_by_tg_id INTEGER NOT NULL,
                payment_id INTEGER NOT NULL,
                plan_code TEXT NOT NULL,
                client_uuid TEXT NOT NULL,
                client_email TEXT NOT NULL,
                sub_id TEXT NOT NULL,
                subscription_url TEXT NOT NULL,
                total_gb INTEGER NOT NULL,
                expires_at_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_services_user
                ON services(user_tg_id, created_at);
            """
        )
        await conn.commit()

    async def upsert_user(self, tg_id: int, username: str | None, full_name: str | None) -> None:
        now = _now()
        await self._conn().execute(
            """
            INSERT INTO telegram_users (tg_id, username, full_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                updated_at = excluded.updated_at
            """,
            (tg_id, username, full_name, now, now),
        )
        await self._conn().commit()

    async def ensure_user(self, tg_id: int) -> None:
        current = await self.get_user(tg_id)
        if current:
            return
        await self.upsert_user(tg_id, None, "")

    async def get_user(self, tg_id: int) -> dict[str, Any] | None:
        async with self._conn().execute("SELECT * FROM telegram_users WHERE tg_id = ?", (tg_id,)) as cursor:
            return _row(await cursor.fetchone())

    async def role_of(self, tg_id: int, admin_ids: set[int]) -> str:
        if tg_id in admin_ids:
            return "admin"
        async with self._conn().execute("SELECT active FROM agents WHERE tg_id = ?", (tg_id,)) as cursor:
            agent = await cursor.fetchone()
        if agent and int(agent["active"]) == 1:
            return "agent"
        return "user"

    async def add_agent(self, tg_id: int, label: str | None = None) -> None:
        now = _now()
        await self.ensure_user(tg_id)
        await self._conn().execute(
            """
            INSERT INTO agents (tg_id, label, active, created_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                label = excluded.label,
                active = 1
            """,
            (tg_id, label, now),
        )
        await self._conn().commit()

    async def list_agents(self) -> list[dict[str, Any]]:
        async with self._conn().execute(
            """
            SELECT agents.tg_id, agents.label, agents.active, agents.created_at,
                   telegram_users.username, telegram_users.full_name
            FROM agents
            LEFT JOIN telegram_users ON telegram_users.tg_id = agents.tg_id
            ORDER BY agents.created_at DESC
            """
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def create_payment(
        self,
        *,
        user_tg_id: int,
        requested_by_tg_id: int,
        plan_code: str,
        amount_toman: int,
        method: str,
        crypto_asset: str | None = None,
        crypto_amount: str | None = None,
        status: str = "draft",
    ) -> int:
        now = _now()
        await self.ensure_user(user_tg_id)
        await self.ensure_user(requested_by_tg_id)
        cursor = await self._conn().execute(
            """
            INSERT INTO payment_requests (
                user_tg_id, requested_by_tg_id, plan_code, amount_toman, method,
                crypto_asset, crypto_amount, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_tg_id,
                requested_by_tg_id,
                plan_code,
                amount_toman,
                method,
                crypto_asset,
                crypto_amount,
                status,
                now,
                now,
            ),
        )
        await self._conn().commit()
        return int(cursor.lastrowid)

    async def attach_payment_proof(self, payment_id: int, proof_type: str, proof_value: str) -> None:
        await self._conn().execute(
            """
            UPDATE payment_requests
            SET proof_type = ?, proof_value = ?, status = 'pending', updated_at = ?
            WHERE id = ?
            """,
            (proof_type, proof_value, _now(), payment_id),
        )
        await self._conn().commit()

    async def get_payment(self, payment_id: int) -> dict[str, Any] | None:
        async with self._conn().execute("SELECT * FROM payment_requests WHERE id = ?", (payment_id,)) as cursor:
            return _row(await cursor.fetchone())

    async def list_pending_payments(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self._conn().execute(
            """
            SELECT *
            FROM payment_requests
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (limit,),
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def list_user_payments(self, tg_id: int, limit: int = 10) -> list[dict[str, Any]]:
        async with self._conn().execute(
            """
            SELECT *
            FROM payment_requests
            WHERE user_tg_id = ? OR requested_by_tg_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (tg_id, tg_id, limit),
        ) as cursor:
            return [dict(row) async for row in cursor]

    async def set_payment_status(self, payment_id: int, status: str, admin_note: str | None = None) -> None:
        await self._conn().execute(
            """
            UPDATE payment_requests
            SET status = ?, admin_note = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, admin_note, _now(), payment_id),
        )
        await self._conn().commit()

    async def create_service(
        self,
        *,
        user_tg_id: int,
        created_by_tg_id: int,
        payment_id: int,
        plan_code: str,
        client_uuid: str,
        client_email: str,
        sub_id: str,
        subscription_url: str,
        total_gb: int,
        expires_at_ms: int,
    ) -> int:
        cursor = await self._conn().execute(
            """
            INSERT INTO services (
                user_tg_id, created_by_tg_id, payment_id, plan_code, client_uuid,
                client_email, sub_id, subscription_url, total_gb, expires_at_ms, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_tg_id,
                created_by_tg_id,
                payment_id,
                plan_code,
                client_uuid,
                client_email,
                sub_id,
                subscription_url,
                total_gb,
                expires_at_ms,
                _now(),
            ),
        )
        await self._conn().commit()
        return int(cursor.lastrowid)

    async def list_services(self, tg_id: int, limit: int = 10) -> list[dict[str, Any]]:
        async with self._conn().execute(
            """
            SELECT *
            FROM services
            WHERE user_tg_id = ? OR created_by_tg_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (tg_id, tg_id, limit),
        ) as cursor:
            return [dict(row) async for row in cursor]

    def _conn(self) -> aiosqlite.Connection:
        if self.conn is None:
            raise RuntimeError("Database.connect() هنوز اجرا نشده است.")
        return self.conn

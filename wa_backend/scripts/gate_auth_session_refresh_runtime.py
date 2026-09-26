from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import jwt
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from api.auth import (  # noqa: E402
    REFRESH_ROTATION_GRACE_SECONDS,
    create_refresh_token,
)
from config import Config  # noqa: E402
from main import app  # noqa: E402
from models import RefreshToken, utc_now  # noqa: E402
from scripts.gate_stage821_live_stock_projector_runtime import (  # noqa: E402
    SessionSU,
)


RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail else "")
    )


async def run() -> None:
    suffix = uuid4().hex[:12]
    company_id: int | None = None
    driver_id: int | None = None

    try:
        async with SessionSU() as su:
            await su.begin()
            company_id = int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO companies
                                (name, company_code, is_active,
                                 subscription_status, currency_code,
                                 timezone, created_at)
                            VALUES
                                ('Session Refresh Gate', :code, true,
                                 'active', 'JOD', 'Asia/Amman', NOW())
                            RETURNING id
                            """
                        ),
                        {"code": f"SRG-{suffix}"},
                    )
                ).scalar_one()
            )
            driver_id = int(
                (
                    await su.execute(
                        text(
                            """
                            INSERT INTO drivers
                                (company_id, username, password_hash,
                                 full_name, is_active, is_admin,
                                 can_allow_debt, max_debt_limit,
                                 created_at)
                            VALUES
                                (:company_id, :username, 'test-only',
                                 'Session Refresh Gate', true, false,
                                 false, 0, NOW())
                            RETURNING id
                            """
                        ),
                        {
                            "company_id": company_id,
                            "username": f"session-{suffix}",
                        },
                    )
                ).scalar_one()
            )
            original_refresh = create_refresh_token(
                {
                    "sub": str(driver_id),
                    "role": "Inventory",
                },
                company_id,
            )
            su.add(
                RefreshToken(
                    token=original_refresh,
                    driver_id=driver_id,
                    expires_at=utc_now() + timedelta(days=30),
                )
            )
            await su.commit()

        transport = ASGITransport(
            app=app,
            raise_app_exceptions=False,
        )
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:

            async def refresh(token: str):
                response = await client.post(
                    "/refresh",
                    json={"refresh_token": token},
                )
                body = response.json()
                return response.status_code, body

            first, second = await asyncio.gather(
                refresh(original_refresh),
                refresh(original_refresh),
            )

            statuses = [first[0], second[0]]
            record(
                "concurrent refresh requests both succeed",
                statuses == [200, 200],
                f"statuses={statuses}",
            )

            successor_a = first[1].get("refresh_token")
            successor_b = second[1].get("refresh_token")
            record(
                "concurrent refresh returns one shared successor token",
                (
                    isinstance(successor_a, str)
                    and successor_a
                    and successor_a == successor_b
                ),
            )

            access_payload = jwt.decode(
                first[1]["token"],
                Config.SECRET_KEY,
                algorithms=["HS256"],
            )
            record(
                "dashboard session role survives refresh rotation",
                access_payload.get("role") == "Inventory",
                f"role={access_payload.get('role')!r}",
            )

            async with SessionSU() as su:
                await su.begin()
                rows = (
                    await su.execute(
                        text(
                            """
                            SELECT id, token, is_revoked, replaced_by_id
                            FROM refresh_tokens
                            WHERE driver_id=:driver_id
                            ORDER BY id
                            """
                        ),
                        {"driver_id": driver_id},
                    )
                ).mappings().all()
                await su.rollback()

            record(
                "rotation creates exactly one active successor",
                (
                    len(rows) == 2
                    and bool(rows[0]["is_revoked"])
                    and int(rows[0]["replaced_by_id"])
                    == int(rows[1]["id"])
                    and not bool(rows[1]["is_revoked"])
                ),
                f"rows={[(r['id'], r['is_revoked'], r['replaced_by_id']) for r in rows]}",
            )

            successor_id = int(rows[1]["id"])
            async with SessionSU() as su:
                await su.begin()
                await su.execute(
                    text(
                        """
                        UPDATE refresh_tokens
                        SET created_at=:stale_created_at
                        WHERE id=:id
                        """
                    ),
                    {
                        "stale_created_at":
                            utc_now()
                            - timedelta(
                                seconds=
                                    REFRESH_ROTATION_GRACE_SECONDS + 2
                            ),
                        "id": successor_id,
                    },
                )
                await su.commit()

            stale_status, _ = await refresh(original_refresh)
            record(
                "old refresh token is rejected after concurrency grace",
                stale_status == 401,
                f"status={stale_status}",
            )

            next_status, next_body = await refresh(successor_a)
            record(
                "current successor still rotates normally",
                (
                    next_status == 200
                    and next_body.get("refresh_token")
                    not in {None, successor_a}
                ),
                f"status={next_status}",
            )

            logout_response = await client.post(
                "/logout",
                headers={
                    "Authorization":
                        f"Bearer {next_body['token']}",
                    "X-Refresh-Token":
                        next_body["refresh_token"],
                },
            )
            record(
                "logout remains valid after chained refresh rotation",
                logout_response.status_code == 200,
                f"status={logout_response.status_code}",
            )

            async with SessionSU() as su:
                await su.begin()
                predecessor = (
                    await su.execute(
                        text(
                            """
                            SELECT replaced_by_id
                            FROM refresh_tokens
                            WHERE token=:token
                            """
                        ),
                        {"token": successor_a},
                    )
                ).mappings().one()
                current_count = int(
                    (
                        await su.execute(
                            text(
                                """
                                SELECT count(*)
                                FROM refresh_tokens
                                WHERE token=:token
                                """
                            ),
                            {
                                "token":
                                    next_body["refresh_token"]
                            },
                        )
                    ).scalar_one()
                )
                await su.rollback()

            record(
                "logout deletes current refresh and clears predecessor link",
                (
                    current_count == 0
                    and predecessor["replaced_by_id"] is None
                ),
                (
                    f"current_count={current_count} "
                    f"predecessor_link={predecessor['replaced_by_id']}"
                ),
            )

    finally:
        if company_id is not None:
            async with SessionSU() as su:
                await su.begin()
                await su.execute(
                    text(
                        "DELETE FROM companies WHERE id=:company_id"
                    ),
                    {"company_id": company_id},
                )
                await su.commit()

    failures = [name for name, ok, _ in RESULTS if not ok]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_CHECK={failure}")

    if failures:
        print("AUTH_SESSION_REFRESH_RUNTIME_GATE=FAIL")
        raise SystemExit(1)

    print("AUTH_SESSION_REFRESH_RUNTIME_GATE=PASS")


if __name__ == "__main__":
    asyncio.run(run())

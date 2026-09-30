"""Read-only V1 staging HTTP driver. Requires Locust on external generator.

NO login/password stored here, NO transfers, sales, imports or other writes.
Run only against an explicitly approved isolated synthetic staging URL.
"""
from __future__ import annotations

from itertools import cycle

from locust import HttpUser, between, events, task

from scripts.staging_load_guard import (
    assert_actual_target,
    read_staging_load_config,
)


# The configured load must pass BOTH the CLI start gate and each user on_start.
# Distinct staging-only tokens are injected by an approved secrets mechanism.
_config = None
_round_robin = cycle((0, 1))


@events.test_start.add_listener
def verify_staging_target(environment, **_kwargs):
    global _config
    config = read_staging_load_config()
    assert_actual_target(environment.host or "", config)
    _config = config


class WanasahReadOnlyStagingUser(HttpUser):
    wait_time = between(0.2, 0.8)

    def on_start(self):
        config = read_staging_load_config()
        assert_actual_target(self.environment.host or self.host, config)
        # One synthetic token per virtual user; no login or token in URLs.
        self.tenant = next(_round_robin) if config.token_b else 0
        self.config = config
        token = config.token_b if self.tenant == 1 else config.token_a
        self.auth_header = {"Authorization": "Bearer " + token}
        self.own_job = config.job_b if self.tenant == 1 else config.job_a
        self.foreign_job = config.job_a if self.tenant == 1 else config.job_b

    def _read(self, path: str, name: str, expected: int):
        with self.client.get(
            path,
            headers=self.auth_header,
            name=name,
            catch_response=True,
            timeout=15,
        ) as response:
            if response.status_code == expected:
                response.success()
            else:
                # Never write response bodies, bearer tokens or private SQL
                # literals into Locust's results/logs.
                response.failure(
                    f"Expected HTTP {expected}; got HTTP {response.status_code}"
                )

    @task(8)
    def read_catalog(self):
        self._read("/simple-products?limit=50",
                   "product.catalog.read", 200)

    @task(2)
    def read_own_import_status(self):
        if self.own_job:
            self._read("/simple-products/imports/" + self.own_job,
                       "product.import.owned", 200)
        else:
            self.read_catalog()

    @task(1)
    def deny_other_company_import(self):
        if self.foreign_job:
            self._read("/simple-products/imports/" + self.foreign_job,
                       "product.import.cross_tenant_404", 404)
        else:
            self.read_catalog()

"""Canonical identities for opt-in database tests; caller owns transactions.

Driver is an operational/FK row only. Owner fixtures require the persisted Owner
link; Field fixtures have their own principal/profile and exact operational map.
No legacy flag or bridge classification participates in selecting an actor.
"""
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from domains.identity.models import BackofficeUser, CompanyOwner, CompanyPrincipal, FieldRepresentative
from domains.identity.migration.models import IdentityLegacyDriverMap
from models import Company, Driver


@dataclass(frozen=True)
class BackofficeFixture:
    context: DashboardRequestContext
    driver_id: int
    operational_driver: SimpleNamespace

    def access(self, db):
        return BackofficeCapabilityAccess(db, BackofficeAuthorizationSubject(
            principal_id=self.context.principal_id,
            backoffice_user_id=self.context.backoffice_user_id,
            company_id=self.context.company_id,
            is_company_owner=self.context.is_company_owner,
            legacy_grant_driver_id=None if self.context.is_company_owner else self.driver_id,
        ))


@dataclass(frozen=True)
class FieldFixture:
    context: FieldRequestContext
    driver: Driver


def _backoffice_fixture(principal, profile, driver, owner_link):
    owner = (owner_link is not None and owner_link.company_id == principal.company_id
             and owner_link.backoffice_user_id == profile.id)
    return BackofficeFixture(
        context=DashboardRequestContext(
            principal_id=principal.id, company_id=principal.company_id,
            backoffice_user_id=profile.id, auth_revision=principal.auth_revision,
            is_company_owner=owner,
        ),
        driver_id=driver.id,
        operational_driver=SimpleNamespace(
            id=driver.id, company_id=principal.company_id, is_active=driver.is_active,
            password_hash=driver.password_hash,
        ),
    )


async def load_company_owner_fixture(db, company_id):
    """Require one active canonical Owner and its exact same-tenant FK locator."""
    result = await db.execute(
        select(CompanyPrincipal, BackofficeUser, Driver, CompanyOwner)
        .join(Company, Company.id == CompanyPrincipal.company_id)
        .join(BackofficeUser, (BackofficeUser.company_id == CompanyPrincipal.company_id)
              & (BackofficeUser.principal_id == CompanyPrincipal.id))
        .join(CompanyOwner, (CompanyOwner.company_id == BackofficeUser.company_id)
              & (CompanyOwner.backoffice_user_id == BackofficeUser.id))
        .join(IdentityLegacyDriverMap,
              (IdentityLegacyDriverMap.company_id == CompanyPrincipal.company_id)
              & (IdentityLegacyDriverMap.backoffice_principal_id == CompanyPrincipal.id)
              & (IdentityLegacyDriverMap.backoffice_user_id == BackofficeUser.id))
        .join(Driver, (Driver.company_id == IdentityLegacyDriverMap.company_id)
              & (Driver.id == IdentityLegacyDriverMap.legacy_driver_id))
        .where(CompanyPrincipal.company_id == company_id,
               CompanyPrincipal.principal_type == "BACKOFFICE",
               CompanyPrincipal.is_active.is_(True), Company.is_active.is_(True),
               BackofficeUser.principal_type == "BACKOFFICE",
               Driver.company_id == company_id, Driver.is_active.is_(True))
    )
    row = result.one_or_none()
    if row is None:
        raise AssertionError("Gate requires an active canonical CompanyOwner with an operational mapping")
    principal, profile, driver, owner_link = row
    return _backoffice_fixture(principal, profile, driver, owner_link)


async def _seed_identity(db, company_id, kind, password):
    # Disjoint ID ranges make equality assumptions fail in real ORM fixtures.
    # Explicit IDs are confined to these opt-in, synthetic test databases.
    suffix = uuid4().int % 100_000_000
    driver = Driver(id=1_300_000_000 + suffix, company_id=company_id,
                    username="fixture-" + uuid4().hex, full_name="Operational fixture",
                    password_hash="synthetic", is_active=True)
    driver.set_password(password)
    principal = CompanyPrincipal(
        id=1_100_000_000 + suffix, company_id=company_id,
        username="principal-" + uuid4().hex, full_name="Canonical fixture",
        password_hash=driver.password_hash, principal_type=kind,
        is_active=True, auth_revision=1,
    )
    profile_type = BackofficeUser if kind == "BACKOFFICE" else FieldRepresentative
    profile = profile_type(id=1_200_000_000 + suffix, company_id=company_id,
                           principal_id=principal.id)
    db.add_all([driver, principal])
    await db.flush()
    db.add(profile)
    await db.flush()
    mapping = dict(company_id=company_id, legacy_driver_id=driver.id)
    if kind == "BACKOFFICE":
        mapping.update(classification="BACKOFFICE_ONLY", backoffice_principal_id=principal.id,
                       backoffice_user_id=profile.id)
    else:
        mapping.update(classification="FIELD_ONLY", field_principal_id=principal.id,
                       field_representative_id=profile.id)
    db.add(IdentityLegacyDriverMap(**mapping))
    await db.flush()
    return principal, profile, driver


async def seed_company_owner_fixture(db, company_id, *, password):
    principal, profile, driver = await _seed_identity(db, company_id, "BACKOFFICE", password)
    db.add(CompanyOwner(company_id=company_id, backoffice_user_id=profile.id))
    await db.flush()
    return await load_company_owner_fixture(db, company_id)


async def seed_ordinary_backoffice_fixture(db, company_id, *, password="SyntheticFixture123"):
    principal, profile, driver = await _seed_identity(db, company_id, "BACKOFFICE", password)
    # No Owner link and no grants: callers explicitly assign the capabilities/scopes
    # needed by their scenario. In particular this fixture cannot pass an Owner gate.
    return _backoffice_fixture(principal, profile, driver, None)


async def seed_field_fixture(db, company_id, *, password="SyntheticFixture123"):
    principal, profile, driver = await _seed_identity(db, company_id, "FIELD_REPRESENTATIVE", password)
    return FieldFixture(FieldRequestContext(
        principal_id=principal.id, representative_id=profile.id,
        company_id=company_id, auth_revision=principal.auth_revision,
    ), driver)

"""Strict, secret-free reviewed mapping format (JSON version 1)."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .errors import BackfillError

CLASSIFICATIONS = {"BACKOFFICE_ONLY", "FIELD_ONLY", "DUAL_SPLIT"}
ENTRY_KEYS = {"company_id", "legacy_driver_id", "classification", "expected_source",
              "source_fingerprint", "backoffice_username", "field_username", "company_owner"}
SOURCE_KEYS = {"company_id", "legacy_driver_id", "username", "full_name", "phone_number",
               "is_active", "is_admin", "can_allow_debt", "max_debt_limit", "backoffice_grants",
               "field_references", "reference_fingerprint"}
GRANT_KEYS = {"company_roles", "location_grants"}
FIELD_KEYS = {"work_sessions", "dispatch_routes", "visits", "shortage_requests", "expected_receivers"}


def fingerprint(facts: dict) -> str:
    return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MappingEntry:
    company_id: int
    legacy_driver_id: int
    classification: str
    expected_source: dict
    source_fingerprint: str
    backoffice_username: str | None
    field_username: str | None
    company_owner: bool

    @property
    def key(self):
        return self.company_id, self.legacy_driver_id


def _positive_id(value):
    return type(value) is int and 0 < value <= 2147483647


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _source(facts):
    if not isinstance(facts, dict) or set(facts) != SOURCE_KEYS:
        raise BackfillError("INVALID_SOURCE_FACTS")
    if not all(_positive_id(facts[k]) for k in ("company_id", "legacy_driver_id")):
        raise BackfillError("INVALID_SOURCE_FACTS")
    for key, limit in (("username", 80), ("full_name", 120), ("phone_number", 20)):
        value = facts[key]
        if value is None and key == "phone_number":
            continue
        if not isinstance(value, str) or len(value) > limit:
            raise BackfillError("INVALID_SOURCE_FACTS")
    if any(type(facts[k]) is not bool for k in ("is_active", "is_admin", "can_allow_debt")):
        raise BackfillError("INVALID_SOURCE_FACTS")
    if not isinstance(facts["max_debt_limit"], str) or not re.fullmatch(r"\d{1,9}\.\d{3}", facts["max_debt_limit"]):
        raise BackfillError("INVALID_SOURCE_FACTS")
    for key, keys in (("backoffice_grants", GRANT_KEYS), ("field_references", FIELD_KEYS)):
        counts = facts[key]
        if (not isinstance(counts, dict) or set(counts) != keys
                or any(type(v) is not int or v < 0 for v in counts.values())):
            raise BackfillError("INVALID_SOURCE_FACTS")
    if not _digest(facts["reference_fingerprint"]):
        raise BackfillError("INVALID_SOURCE_FACTS")


def validate_document(document: dict) -> tuple[MappingEntry, ...]:
    """Reject unknown fields, unresolved proposals and implicit Owner selection."""
    if (not isinstance(document, dict) or set(document) != {"format_version", "reviewed", "entries"}
            or type(document["format_version"]) is not int or document["format_version"] != 1):
        raise BackfillError("INVALID_MAPPING_FORMAT")
    if document["reviewed"] is not True:
        raise BackfillError("REVIEWED_MAPPING_REQUIRED")
    if not isinstance(document["entries"], list):
        raise BackfillError("INVALID_MAPPING_FORMAT")
    entries, seen, usernames, owners = [], set(), set(), {}
    for raw in document["entries"]:
        if not isinstance(raw, dict) or set(raw) != ENTRY_KEYS:
            raise BackfillError("INVALID_MAPPING_ENTRY")
        if not all(_positive_id(raw[k]) for k in ("company_id", "legacy_driver_id")):
            raise BackfillError("INVALID_ID")
        kind = raw["classification"]
        if not isinstance(kind, str) or kind not in CLASSIFICATIONS:
            raise BackfillError("UNRESOLVED_CLASSIFICATION")
        if type(raw["company_owner"]) is not bool:
            raise BackfillError("EXPLICIT_OWNER_REQUIRED")
        if raw["company_owner"] and kind == "FIELD_ONLY":
            raise BackfillError("FIELD_ONLY_OWNER_FORBIDDEN")
        _source(raw["expected_source"])
        if (not _digest(raw["source_fingerprint"])
                or fingerprint(raw["expected_source"]) != raw["source_fingerprint"]
                or any(raw[k] != raw["expected_source"][k] for k in ("company_id", "legacy_driver_id"))):
            raise BackfillError("INVALID_SOURCE_FINGERPRINT")
        for key, required in (("backoffice_username", kind != "FIELD_ONLY"),
                              ("field_username", kind != "BACKOFFICE_ONLY")):
            value = raw[key]
            if required:
                if not isinstance(value, str) or not value.strip() or len(value) > 80 or "\x00" in value:
                    raise BackfillError("TARGET_USERNAME_REQUIRED")
                pair = raw["company_id"], value
                if pair in usernames:
                    raise BackfillError("DUPLICATE_TARGET_USERNAME")
                usernames.add(pair)
            elif value is not None:
                raise BackfillError("UNEXPECTED_TARGET_USERNAME")
        entry = MappingEntry(**raw)
        if entry.key in seen:
            raise BackfillError("DUPLICATE_LEGACY_KEY")
        seen.add(entry.key)
        owners[entry.company_id] = owners.get(entry.company_id, 0) + int(entry.company_owner)
        entries.append(entry)
    if any(count != 1 for count in owners.values()):
        raise BackfillError("EXACTLY_ONE_OWNER_REQUIRED")
    return tuple(sorted(entries, key=lambda e: e.key))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BackfillError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def load_mapping(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise BackfillError("MAPPING_FILE_UNREADABLE") from None

"""Stable identity families, independent of capabilities and role names."""
from enum import Enum


class PrincipalType(str, Enum):
    BACKOFFICE = "BACKOFFICE"
    FIELD_REPRESENTATIVE = "FIELD_REPRESENTATIVE"

"""Company authentication-session contracts.

This package is intentionally persistence-free. HTTP dependencies and refresh-row
rotation/cutover remain separate integration phases.
"""

from .claims import CompanyTokenClaims, TokenContractError
from .codec import decode_company_token, issue_access_token, issue_refresh_token

__all__ = [
    "CompanyTokenClaims",
    "TokenContractError",
    "decode_company_token",
    "issue_access_token",
    "issue_refresh_token",
]

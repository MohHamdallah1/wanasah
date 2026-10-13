from __future__ import annotations

from pathlib import Path
import sys
import unittest
from uuid import uuid4

from pydantic import ValidationError


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from api.representatives.schemas import (  # noqa: E402
    RepresentativeCreateRequest,
    RepresentativeCredentialResetRequest,
    RepresentativeUpdateRequest,
)


def create_payload(**overrides):
    payload = {
        "request_id": uuid4(),
        "full_name": "Contract Representative",
        "username": "rep_12",
        "phone_number": " 0790000000 ",
        "password": "password8",
        "can_allow_debt": False,
        "max_debt_limit": "0.000",
    }
    payload.update(overrides)
    return payload


class RepresentativeFormIdentityContractTests(unittest.TestCase):
    def test_create_phone_is_required_nonblank_and_trimmed(self):
        payload = create_payload()
        del payload["phone_number"]
        with self.assertRaises(ValidationError):
            RepresentativeCreateRequest.model_validate(payload)
        with self.assertRaises(ValidationError):
            RepresentativeCreateRequest.model_validate(create_payload(phone_number="   "))
        parsed = RepresentativeCreateRequest.model_validate(create_payload())
        self.assertEqual(parsed.phone_number, "0790000000")

    def test_update_phone_cannot_be_cleared_but_may_be_omitted(self):
        with self.assertRaises(ValidationError):
            RepresentativeUpdateRequest.model_validate({"request_id": uuid4(), "phone_number": None})
        with self.assertRaises(ValidationError):
            RepresentativeUpdateRequest.model_validate({"request_id": uuid4(), "phone_number": "   "})
        parsed = RepresentativeUpdateRequest.model_validate(
            {"request_id": uuid4(), "full_name": "Changed"}
        )
        self.assertNotIn("phone_number", parsed.model_fields_set)

    def test_username_accepts_one_script_with_digits_and_separators(self):
        for username in (
            "محمد",
            "محمد12",
            "مندوب_12",
            "mohammad",
            "mohammad12",
            "rep_12",
            "rep-12",
            "rep.12",
        ):
            with self.subTest(username=username):
                parsed = RepresentativeCreateRequest.model_validate(
                    create_payload(username=f"  {username}  ")
                )
                self.assertEqual(parsed.username, username)

    def test_username_rejects_mixed_scripts_digits_only_separators_and_whitespace(self):
        for username in (
            "محمدmohammad",
            "repمحمد",
            "مohammad",
            "123456",
            "._-",
            "rep 12",
            "مندوب 12",
        ):
            with self.subTest(username=username):
                with self.assertRaises(ValidationError):
                    RepresentativeCreateRequest.model_validate(create_payload(username=username))

    def test_create_password_accepts_unicode_and_exact_72_utf8_bytes(self):
        valid = (
            "محمدمحمد",
            "password8",
            "محمدAbc123!",
            "a" * 70 + "م",
        )
        for password in valid:
            with self.subTest(password=password, utf8=len(password.encode("utf-8"))):
                parsed = RepresentativeCreateRequest.model_validate(create_payload(password=password))
                self.assertEqual(parsed.password, password)
        self.assertEqual(len(("a" * 70 + "م").encode("utf-8")), 72)

    def test_create_password_rejects_short_and_over_72_utf8_bytes(self):
        for password in ("short7", "a" * 71 + "م", "م" * 37):
            with self.subTest(characters=len(password), utf8=len(password.encode("utf-8"))):
                with self.assertRaises(ValidationError):
                    RepresentativeCreateRequest.model_validate(create_payload(password=password))

    def test_reset_password_uses_same_utf8_byte_boundary(self):
        exact = "a" * 70 + "م"
        parsed = RepresentativeCredentialResetRequest.model_validate(
            {"request_id": uuid4(), "new_password": exact}
        )
        self.assertEqual(parsed.new_password, exact)
        with self.assertRaises(ValidationError):
            RepresentativeCredentialResetRequest.model_validate(
                {"request_id": uuid4(), "new_password": "a" * 71 + "م"}
            )


if __name__ == "__main__":
    unittest.main()

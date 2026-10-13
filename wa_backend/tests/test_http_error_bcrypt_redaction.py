import json

from observability.http_errors import build_http_server_error_event


def test_unlabelled_bcrypt_db_parameter_is_redacted_from_http_error_evidence():
    bcrypt_hash = "$2b$12$" + "A" * 53
    event = build_http_server_error_event(
        request_id="bcrypt-redaction-proof",
        status_code=500,
        error_code="INTERNAL_SERVER_ERROR",
        method="POST",
        path="/representatives/1/credentials/reset",
        client_ip="127.0.0.1",
        exc=RuntimeError(f"DBAPI failure [parameters: ({bcrypt_hash!r}, 1)]"),
        handled_http_exception=False,
    )

    rendered = json.dumps(event, ensure_ascii=False)
    assert bcrypt_hash not in rendered
    assert "***REDACTED_BCRYPT***" in rendered

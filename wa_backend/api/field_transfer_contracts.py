"""Batch-only FIELD error adaptation. No mutation, authorization or replay logic."""
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

_VALIDATION_CODES = {
    "FIELD_TRANSFER_DUPLICATE_ID",
    "FIELD_TRANSFER_REJECTION_REASON_REQUIRED",
}


def transfer_batch_error(status, code, message, transfer_id=None):
    context = {}
    if type(transfer_id) is int and transfer_id > 0:
        context["transfer_id"] = transfer_id
    return HTTPException(status_code=status, detail={
        "code": code, "message": message, "context": context,
    })


def attributed_transfer_error(error, transfer_id, fallback_code):
    """Only called around an operation on one known public transfer."""
    if not 400 <= error.status_code < 500 or error.status_code in (408, 429):
        return error
    detail = error.detail if isinstance(error.detail, dict) else {}
    code = detail.get("code")
    if not isinstance(code, str) or not code:
        code = fallback_code
    return transfer_batch_error(error.status_code, code,
        "This transfer cannot complete the batch decision.", transfer_id)


class FieldTransferBatchRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError as error:
                for issue in error.errors():
                    if issue.get("type") in _VALIDATION_CODES:
                        context = issue.get("ctx") or {}
                        raise transfer_batch_error(422, issue["type"],
                            "The batch decision input is invalid.",
                            context.get("transfer_id")) from None
                raise
        return handler


def field_transfer_batch_route(router):
    """Register only the existing batch URL with its narrow validation adapter."""
    def register(endpoint):
        router.add_api_route("/driver/transfers/batch_respond", endpoint,
            methods=["PUT"], status_code=200, route_class_override=FieldTransferBatchRoute)
        return endpoint
    return register

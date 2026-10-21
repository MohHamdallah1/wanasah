"""Public application seam. All functions use the caller's transaction."""
from .contracts import MANAGE, READ, ExactAmount, ManualReferenceWrite
from .errors import PurchaseReferenceError
from .inbound import (
    begin_receipt_reference, inbound_reference_prefill, receipt_hash_arguments,
    select_reference_pairs, write_receipt_references,
)
from .repository import acquire_operation_guard, acquire_writer_guard
from .values import currency_value
from .service import read_reference, write_manual_reference

__all__ = [
    "MANAGE", "READ", "ExactAmount", "ManualReferenceWrite", "PurchaseReferenceError",
    "begin_receipt_reference", "inbound_reference_prefill", "receipt_hash_arguments",
    "select_reference_pairs", "write_receipt_references",
    "acquire_operation_guard", "currency_value", "acquire_writer_guard",
    "read_reference", "write_manual_reference",
]

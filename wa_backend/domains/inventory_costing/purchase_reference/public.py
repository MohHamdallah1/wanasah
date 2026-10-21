"""Public application seam. All functions use the caller's transaction."""
from .contracts import MANAGE, READ, ManualReferenceWrite
from .errors import PurchaseReferenceError
from .inbound import (
    begin_receipt_reference, inbound_reference_prefill, receipt_hash_arguments,
    select_reference_pairs, write_receipt_references,
)
from .repository import acquire_writer_guard
from .service import read_reference, write_manual_reference

__all__ = [
    "MANAGE", "READ", "ManualReferenceWrite", "PurchaseReferenceError",
    "begin_receipt_reference", "inbound_reference_prefill", "receipt_hash_arguments",
    "select_reference_pairs", "write_receipt_references",
    "acquire_writer_guard", "read_reference", "write_manual_reference",
]

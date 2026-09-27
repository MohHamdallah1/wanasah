"""Bounded upload streaming for Product Import HTTP sources."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import tempfile
from typing import BinaryIO


UPLOAD_READ_CHUNK = (
    64
    * 1024
)
UPLOAD_SPOOL_MEMORY_LIMIT = (
    256
    * 1024
)


@dataclass(slots=True)
class BoundedUpload:
    stream: BinaryIO
    byte_size: int
    sha256: str

    def close(
        self,
    ) -> None:
        self.stream.close()


class ProductImportUploadTooLarge(
    RuntimeError
):
    pass


async def spool_upload_bounded(
    upload,
    *,
    max_bytes: int,
) -> BoundedUpload:
    if int(
        max_bytes
    ) <= 0:
        raise ValueError(
            "max_bytes must be positive."
        )

    spool = tempfile.SpooledTemporaryFile(
        max_size=
            UPLOAD_SPOOL_MEMORY_LIMIT,
        mode="w+b",
    )
    digest = hashlib.sha256()
    total = 0

    try:
        while True:
            chunk = await upload.read(
                UPLOAD_READ_CHUNK
            )
            if not chunk:
                break

            total += len(
                chunk
            )
            if total > int(
                max_bytes
            ):
                raise ProductImportUploadTooLarge(
                    "Product Import upload exceeds the configured size limit."
                )

            digest.update(
                chunk
            )
            spool.write(
                chunk
            )

        spool.seek(
            0
        )
        return BoundedUpload(
            stream=spool,
            byte_size=total,
            sha256=
                digest.hexdigest(),
        )
    except Exception:
        spool.close()
        raise

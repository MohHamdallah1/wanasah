"""Correction file headers and locale contract tests."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from openpyxl import load_workbook
from domains.simple_products.imports.application import correction_service as service
from domains.simple_products.imports.application.state_machine import JobStatus
from domains.simple_products.imports.domain.errors import (
    ProductImportTerminalError, user_safe_row_error_message,
)

CODES=(
    "IMPORT_PACKAGING_INVALID", "IMPORT_BARCODE_DUPLICATE",
    "IMPORT_NAME_REQUIRED", "IMPORT_NAME_TOO_LONG",
    "SIMPLE_PRODUCT_PACKAGE_UOM_UNSUPPORTED", "IMPORT_PACKAGING_REQUIRED",
    "SIMPLE_PRODUCT_PACKAGE_PRICE_WITHOUT_PACKAGE",
    "IMPORT_PACKAGE_BARCODE_WITHOUT_PACKAGE",
    "SIMPLE_PRODUCT_PRICE_REQUIRED", "SIMPLE_PRODUCT_PRICE_INVALID",
    "IMPORT_BARCODE_NUMERIC_UNSAFE", "IMPORT_BARCODE_SCIENTIFIC_NOTATION",
    "PRODUCT_TRACKING_MODE_INVALID",
)


class CorrectionArtifactLocaleTests(unittest.IsolatedAsyncioTestCase):
    def test_plain_headers_and_collisions(self):
        self.assertEqual(service.CORRECTION_META_HEADERS, (
            "row_identity", "original_row", "error_code", "error_field", "error_message",
        ))
        self.assertEqual(
            service._artifact_headers(["اسم المنتج", "سعر الوحدة"]),
            [*service.CORRECTION_META_HEADERS, "اسم المنتج", "سعر الوحدة"],
        )
        for header in ("row_identity", "__wanasah_row_identity"):
            with self.subTest(header=header), self.assertRaises(ProductImportTerminalError):
                service._artifact_headers([header])

    def test_owner_thirteen_codes_have_specific_localized_messages(self):
        for code in CODES:
            with self.subTest(code=code):
                ar=user_safe_row_error_message(code,locale="ar-JO")
                en=user_safe_row_error_message(code,locale="en-US")
                self.assertNotEqual(ar,en)
                self.assertTrue(any("\u0600" <= c <= "\u06ff" for c in ar))
                self.assertNotIn("This row contains invalid",en)
        self.assertIn("سعر",user_safe_row_error_message("SIMPLE_PRODUCT_PRICE_INVALID",locale="ar"))
        self.assertIn("العبوة",user_safe_row_error_message("SIMPLE_PRODUCT_PACKAGE_UOM_UNSUPPORTED",locale="ar"))

    def test_old_and_new_correction_csv_roundtrip(self):
        identity=uuid4()
        originals=["اسم المنتج", "سعر الوحدة"]
        for meta in (service.CORRECTION_META_HEADERS,service.LEGACY_CORRECTION_META_HEADERS):
            with self.subTest(meta=meta[0]):
                stream=StringIO(newline="")
                writer=csv.writer(stream)
                writer.writerow([*meta,*originals])
                writer.writerow([str(identity),9,"IMPORT_NAME_REQUIRED","name","Safe","قهوة","1.50"])
                patches=service.parse_correction_payload(
                    file_name="correction.csv",
                    payload=("\ufeff"+stream.getvalue()).encode("utf-8"),
                    source_headers=originals,
                )
                self.assertEqual(len(patches),1)
                self.assertEqual(patches[0].row_identity,identity)
                self.assertEqual(patches[0].raw_data,{"اسم المنتج":"قهوة","سعر الوحدة":"1.50"})

    def test_mixed_metadata_is_rejected(self):
        headers=[*service.CORRECTION_META_HEADERS,"اسم المنتج"]
        headers[0]=service.LEGACY_CORRECTION_IDENTITY_HEADER
        stream=StringIO()
        writer=csv.writer(stream)
        writer.writerow(headers)
        writer.writerow([str(uuid4()),9,"IMPORT_NAME_REQUIRED","name","Safe","قهوة"])
        with self.assertRaises(ProductImportTerminalError):
            service.parse_correction_payload(
                file_name="correction.csv",
                payload=stream.getvalue().encode("utf-8"),
                source_headers=["اسم المنتج"],
            )

    async def test_generated_csv_and_xlsx_localize_without_losing_identity(self):
        identity=uuid4()
        job_id=uuid4()
        job=SimpleNamespace(
            status=JobStatus.COMPLETED_WITH_ERRORS.value,
            finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
            detected_headers=["اسم المنتج","سعر الوحدة"],
        )
        item=SimpleNamespace(
            row_identity=identity,row_number=23,error_code="SIMPLE_PRODUCT_PRICE_INVALID",
            raw_data={"اسم المنتج":"قهوة","سعر الوحدة":"-1"},compacted_at=None,
        )
        for format_name,locale in (("csv","ar-JO"),("xlsx","ar-JO"),("xlsx","en-US")):
            with self.subTest(file_format=format_name,locale=locale):
                with (
                    patch.object(service,"open_tenant_session",AsyncMock(return_value=(None,object()))),
                    patch.object(service,"close_tenant_session",AsyncMock()),
                    patch.object(service,"load_job",AsyncMock(return_value=job)),
                    patch.object(service,"fetch_failed_rows_batch",AsyncMock(side_effect=[[item],[]])),
                ):
                    artifact=await service.build_correction_artifact(
                        company_id=38,job_id=job_id,file_format=format_name,locale=locale,
                    )
                self.assertEqual(artifact.row_count,1)
                if format_name=="csv":
                    rows=list(csv.reader(StringIO(artifact.payload.decode("utf-8-sig"))))
                else:
                    book=load_workbook(BytesIO(artifact.payload),read_only=True,data_only=True)
                    try:
                        rows=list(book.active.values)
                    finally:
                        book.close()
                self.assertEqual(tuple(rows[0][:5]),service.CORRECTION_META_HEADERS)
                self.assertEqual(rows[1][0],str(identity))
                self.assertEqual(rows[1][2],"SIMPLE_PRODUCT_PRICE_INVALID")
                self.assertEqual(rows[1][4],user_safe_row_error_message(
                    "SIMPLE_PRODUCT_PRICE_INVALID",locale=locale,
                ))
                self.assertNotIn("__wanasah_","|".join(str(x) for x in rows[0]))
                patches=service.parse_correction_payload(
                    file_name=artifact.file_name,
                    payload=artifact.payload,
                    source_headers=job.detected_headers,
                )
                self.assertEqual(len(patches),1)
                self.assertEqual(patches[0].row_identity,identity)
                self.assertEqual(patches[0].raw_data,{"اسم المنتج":"قهوة","سعر الوحدة":"-1"})


if __name__ == "__main__":
    unittest.main()

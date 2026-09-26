import {
  readFileSync,
} from "node:fs";
import {
  describe,
  expect,
  it,
} from "vitest";

const read = (relativePath: string) =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  );

describe("Products P9.4 import workflow", () => {
  it("keeps the modal as a staged composition layer", () => {
    const modal = read(
      "../pages/products/import/ImportProductModal.tsx",
    );

    expect(modal).toContain(
      "<ImportStageRail",
    );
    expect(modal).toContain(
      "<ImportProductStartPanel",
    );
    expect(modal).toContain(
      "<ImportProductMappingPanel",
    );
    expect(modal).toContain(
      "<ImportProductStatusPanel",
    );
    expect(modal).not.toContain(
      "setInterval(",
    );
    expect(modal).not.toContain(
      "sessionStorage",
    );
    expect(modal).not.toContain(
      '"/retry"',
    );
  });

  it("shows four compact import phases derived only from existing job and status state", () => {
    const rail = read(
      "../pages/products/import/ImportStageRail.tsx",
    );

    for (const stage of [
      '"upload"',
      '"mapping"',
      '"processing"',
      '"result"',
    ]) {
      expect(rail).toContain(stage);
    }
    expect(rail).toContain(
      'status?.status === "NEEDS_MAPPING"',
    );
    expect(rail).toContain(
      'status?.status === "COMPLETED"',
    );
    expect(rail).toContain(
      'status?.status === "FAILED"',
    );
    expect(rail).toContain(
      'status?.status === "VALIDATION_FAILED"',
    );
    expect(rail).toContain(
      'aria-current={',
    );
  });

  it("keeps upload and tracking choices compact while preserving the existing callbacks", () => {
    const start = read(
      "../pages/products/import/ImportProductStartPanel.tsx",
    );

    expect(start).toContain(
      "onChooseFile(",
    );
    expect(start).toContain(
      "onStartImport",
    );
    expect(start).toContain(
      "<ProductTrackingFields",
    );
    expect(start).toContain(
      "onResetTracking",
    );
    expect(start).toContain(
      'accept=".csv,.xlsx',
    );
    expect(start).not.toContain(
      "min-h-48",
    );
  });

  it("keeps canonical mapping fields and bounded status outcomes explicit", () => {
    const fields = read(
      "../pages/products/import/importFields.ts",
    );
    const mapping = read(
      "../pages/products/import/ImportProductMappingPanel.tsx",
    );
    const status = read(
      "../pages/products/import/ImportProductStatusPanel.tsx",
    );

    for (const field of [
      "name",
      "family",
      "package_uom",
      "units_per_package",
      "package_price",
      "unit_price",
      "unit_barcode",
      "package_barcode",
      "lot_control_mode",
      "expiry_control_mode",
    ]) {
      expect(fields).toContain(
        '"' + field + '"',
      );
    }

    expect(mapping).toContain(
      "IMPORT_MAPPING_FIELDS.map",
    );
    expect(mapping).toContain(
      "onSubmitMapping",
    );

    for (const statusName of [
      "VALIDATION_FAILED",
      "FAILED",
      "COMPLETED",
    ]) {
      expect(status).toContain(
        '"' + statusName + '"',
      );
    }
    expect(status).toContain(
      "onRetryPoll",
    );
    expect(status).toContain(
      "onRetryImport",
    );
    expect(status).toContain(
      "onDownloadErrorReport",
    );
  });

  it("leaves worker polling resume retry and paginated error download authorities unchanged", () => {
    const polling = read(
      "../pages/products/import/useImportProductPolling.ts",
    );
    const resume = read(
      "../pages/products/import/useImportSessionResume.ts",
    );
    const commands = read(
      "../pages/products/import/useImportProductCommands.ts",
    );
    const downloads = read(
      "../pages/products/import/createImportDownloads.ts",
    );

    expect(polling).toContain(
      "setTimeout(",
    );
    expect(resume).toContain(
      "sessionStorage.getItem",
    );
    expect(commands).toContain(
      '"/retry"',
    );
    expect(downloads).toContain(
      "limit=1000",
    );
    expect(downloads).toContain(
      "result.next_after_row",
    );
  });
});

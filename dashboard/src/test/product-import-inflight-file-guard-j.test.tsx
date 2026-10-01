import { createRef } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { TFunction } from "i18next";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { dir: () => "ltr" } }),
}));

import { createImportFileActions } from "@/pages/products/import/createImportFileActions";
import { ImportProductStartPanel } from "@/pages/products/import/ImportProductStartPanel";

const t = ((key: string) => key) as TFunction;

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

describe("Product Import in-flight file ownership", () => {
  it("cannot reset durable job/session state by selecting another file", () => {
    const setImportFile = vi.fn();
    const setImportJobId = vi.fn();
    const setImportStatus = vi.fn();
    const setMapping = vi.fn();
    const key = "synthetic-import-session";
    sessionStorage.setItem(key, "old-job");
    const actions = createImportFileActions({
      importSessionKey: key,
      importing: true,
      trackingDefaultsQuery: {},
      fileRef: createRef<HTMLInputElement>(),
      setImportOpen: vi.fn(),
      setImportFile,
      setImportJobId,
      setImportStatus,
      setImportPollError: vi.fn(),
      setMapping,
      setImportLotControlMode: vi.fn(),
      setImportExpiryControlMode: vi.fn(),
      setImportTrackingExpanded: vi.fn(),
      t,
    });

    actions.chooseFile(new File(["Product name\nCoffee"], "next.csv"));
    expect(setImportFile).not.toHaveBeenCalled();
    expect(setImportJobId).not.toHaveBeenCalled();
    expect(setImportStatus).not.toHaveBeenCalled();
    expect(setMapping).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(key)).toBe("old-job");
  });

  it("disables file input/drop zone while upload is pending", () => {
    const onChooseFile = vi.fn();
    const onDraggingChange = vi.fn();
    const view = render(<ImportProductStartPanel
      importing={true}
      online={true}
      file={new File(["Product name\nCoffee"], "upload.csv")}
      dragging={false}
      lotControlMode="NONE"
      expiryControlMode="NONE"
      trackingDefaultsLoading={false}
      trackingDefaultsError={false}
      trackingUsesCompanyDefaults={true}
      trackingExpanded={false}
      fileRef={createRef<HTMLInputElement>()}
      onDownloadTemplate={vi.fn()}
      onRetryTrackingDefaults={vi.fn()}
      onExpandTracking={vi.fn()}
      onLotControlModeChange={vi.fn()}
      onExpiryControlModeChange={vi.fn()}
      onResetTracking={vi.fn()}
      onChooseFile={onChooseFile}
      onDraggingChange={onDraggingChange}
      onStartImport={vi.fn()}
    />);
    const input = view.container.querySelector("input[type=file]") as HTMLInputElement;
    const dropZone = screen.getByRole("button", { name: /upload\.csv/ }) as HTMLButtonElement;
    expect(input.disabled).toBe(true);
    expect(dropZone.disabled).toBe(true);
    fireEvent.drop(dropZone, {
      dataTransfer: { files: [new File(["x"], "another.csv")] },
    });
    expect(onChooseFile).not.toHaveBeenCalled();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import type { TFunction } from "i18next";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));
vi.mock("react-i18next", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-i18next")>();
  return {
    ...original,
    useTranslation: () => ({
      t: (key: string) => key,
      i18n: { exists: () => false },
    }),
  };
});
vi.mock("@/lib/durableOperations", () => ({
  fileFingerprint: vi.fn(async () => "same-content-hash"),
  getOrCreateDurableCommand: vi.fn(async () => ({ requestId: REQUEST_ID })),
  completeDurableOperation: vi.fn(),
  abandonDurableOperation: vi.fn(),
}));

import { toast } from "sonner";
import {
  abandonDurableOperation,
  completeDurableOperation,
  getOrCreateDurableCommand,
} from "@/lib/durableOperations";
import { useImportCorrection } from "@/pages/products/import/useImportCorrection";
import { ImportProductStatusPanel } from "@/pages/products/import/ImportProductStatusPanel";
import type { ProductImportState } from "@/pages/products/contracts";

const JOB = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const REQUEST_ID = "33333333-3333-4333-8333-333333333333";

function setup(authFetch: (path: string, options?: RequestInit) => Promise<unknown>) {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  const setImportPollKey = vi.fn();
  const setImportStatus = vi.fn();
  function wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  const view = renderHook(({ jobId }) => useImportCorrection({
    companyId: 38,
    driverId: 17,
    jobId,
    online: true,
    authFetch,
    downloadCorrection: vi.fn(async () => undefined),
    setImportPollKey,
    setImportStatus,
    t: ((key: string) => key) as TFunction,
  }), {
    wrapper,
    initialProps: { jobId: JOB },
  });
  return { ...view, setImportPollKey, setImportStatus };
}

const file = new File(["corrected rows"], "product-import-correction.xlsx", {
  type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("same-job Product Import correction frontend", () => {
  it("resends a lost-response POST with identical file and request id without starting a new import", async () => {
    const fetch = vi.fn()
      .mockRejectedValueOnce({ status: 0, code: "NETWORK_UNAVAILABLE" })
      .mockResolvedValueOnce({
        job_id: JOB, status: "VALIDATING", corrected_rows: 3, replayed: true,
      });
    const view = setup(fetch);

    act(() => view.result.current.chooseCorrectionFile(file));
    act(() => view.result.current.uploadCorrection());
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(view.result.current.uploadingCorrection).toBe(false));
    expect(completeDurableOperation).not.toHaveBeenCalled();
    expect(abandonDurableOperation).not.toHaveBeenCalled();

    act(() => view.result.current.uploadCorrection());
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(view.setImportPollKey).toHaveBeenCalledTimes(1));
    for (const [path, options] of fetch.mock.calls) {
      expect(path).toBe("/simple-products/imports/" + JOB + "/correction");
      expect(options.method).toBe("POST");
      const form = options.body as FormData;
      expect(form.get("request_id")).toBe(REQUEST_ID);
      expect(form.get("file")).toBe(file);
    }
    expect(getOrCreateDurableCommand).toHaveBeenCalledTimes(2);
    expect(completeDurableOperation).toHaveBeenCalledTimes(1);
    expect(view.setImportStatus).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("does not accept another job id or mutate current job on wrong-job ACK", async () => {
    const fetch = vi.fn().mockResolvedValue({
      job_id: OTHER, status: "VALIDATING", corrected_rows: 1, replayed: false,
    });
    const view = setup(fetch);
    act(() => view.result.current.chooseCorrectionFile(file));
    act(() => view.result.current.uploadCorrection());
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(view.setImportPollKey).not.toHaveBeenCalled();
    expect(view.setImportStatus).not.toHaveBeenCalled();
    expect(completeDurableOperation).not.toHaveBeenCalled();
    view.unmount();
  });

  it("releases the pending local command only on a known zero-write validation rejection", async () => {
    const fetch = vi.fn().mockRejectedValue({ status: 422, code: "PRODUCT_IMPORT_CORRECTION_INVALID" });
    const view = setup(fetch);
    act(() => view.result.current.chooseCorrectionFile(file));
    act(() => view.result.current.uploadCorrection());
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(abandonDurableOperation).toHaveBeenCalledTimes(1);
    view.unmount();
  });

  it("offers correction in terminal rejected-row states, never on an active/complete import", () => {
    const current = {
      job_id: JOB, status: "VALIDATION_FAILED",
      valid_rows: 0, imported_rows: 0, invalid_rows: 3,
      import_failed_rows: 0, failed_rows: 3, errors: [],
      default_lot_control_mode: "NONE", default_expiry_control_mode: "NONE",
    } as ProductImportState;
    const actions = {
      status: current,
      pollError: null,
      progress: 0,
      online: true,
      retryPending: false,
      cancelPending: false,
      onCancelImport: vi.fn(),
      onRetryPoll: vi.fn(),
      onDownloadErrorReport: vi.fn(),
      correctionFile: null,
      correctionFileRef: { current: null },
      downloadingCorrection: false,
      uploadingCorrection: false,
      onChooseCorrectionFile: vi.fn(),
      onDownloadCorrection: vi.fn(),
      onUploadCorrection: vi.fn(),
      onResetImport: vi.fn(),
      onRetryImport: vi.fn(),
      onCompletedClose: vi.fn(),
    };
    const view = render(<ImportProductStatusPanel {...actions} />);
    fireEvent.click(screen.getByRole("button", { name: "products.correction.download" }));
    expect(actions.onDownloadCorrection).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "products.correction.upload" })).toBeDisabled();

    view.rerender(<ImportProductStatusPanel {...actions} status={{
      ...current, status: "COMPLETED_WITH_ERRORS", imported_rows: 5,
    }} />);
    expect(screen.getByRole("button", { name: "products.correction.download" })).not.toBeNull();

    view.rerender(<ImportProductStatusPanel {...actions} status={{
      ...current, status: "COMPLETED",
    }} />);
    expect(screen.queryByRole("button", { name: "products.correction.download" })).toBeNull();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";
import type { TFunction } from "i18next";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    warning: vi.fn(),
    message: vi.fn(),
    error: vi.fn(),
  },
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

import { toast } from "sonner";
import { useImportProductCommands } from "@/pages/products/import/useImportProductCommands";
import { ImportProductStatusPanel } from "@/pages/products/import/ImportProductStatusPanel";
import type { ProductImportState } from "@/pages/products/contracts";

const JOB = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function commands(authFetch: (path: string, opts?: RequestInit) => Promise<unknown>) {
  const setStatus = vi.fn();
  const setError = vi.fn();
  const setPollKey = vi.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  }
  const hook = renderHook(({jobId}) => useImportProductCommands({
    importJobId: jobId,
    mapping: {},
    setMapping: vi.fn(),
    authFetch,
    setImportPollError: setError,
    setImportStatus: setStatus,
    setImportPollKey: setPollKey,
    t: ((key: string) => key) as TFunction,
  }), { wrapper, initialProps: { jobId: JOB } });
  return { ...hook, setStatus, setError, setPollKey };
}

describe("Product Import cancellation connects the existing tenant-scoped backend", () => {
  it("requires confirmation and sends exactly one scoped POST before updating the watch", async () => {
    const fetch = vi.fn().mockResolvedValue({
      job_id: JOB,
      status: "CANCELLED",
      message: "Import cancellation accepted.",
    });
    const accept = vi.spyOn(window, "confirm").mockReturnValue(false);
    const hook = commands(fetch);

    act(() => hook.result.current.cancelImport());
    expect(accept).toHaveBeenCalledWith("products.importCancelConfirm");
    expect(fetch).not.toHaveBeenCalled();

    accept.mockReturnValue(true);
    act(() => hook.result.current.cancelImport());
    await waitFor(() => expect(hook.setPollKey).toHaveBeenCalledTimes(1));
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith(
      "/simple-products/imports/" + JOB + "/cancel",
      { method: "POST" },
    );
    expect(hook.setError).toHaveBeenCalledWith(null);
    expect(hook.setStatus).toHaveBeenCalledTimes(1);
    expect(toast.message).toHaveBeenCalledWith("products.importCancelRequested");
    hook.unmount();
  });

  it("rejects a reply referencing another job without mutating import state", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetch = vi.fn().mockResolvedValue({
      job_id: OTHER,
      status: "CANCELLED",
      message: "other job",
    });
    const hook = commands(fetch);
    act(() => hook.result.current.cancelImport());
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(hook.setStatus).not.toHaveBeenCalled();
    expect(hook.setPollKey).not.toHaveBeenCalled();
    hook.unmount();
  });

  it("does not apply a late cancel response to a replacement import job", async () => {
    let resolveOld!: (response: unknown) => void;
    const pending = new Promise<unknown>((resolve) => {
      resolveOld = resolve;
    });
    const fetch = vi.fn().mockReturnValue(pending);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const hook = commands(fetch);

    act(() => hook.result.current.cancelImport());
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    hook.rerender({ jobId: OTHER });
    await act(async () => {
      resolveOld({
        job_id: JOB,
        status: "CANCELLED",
        message: "Old job was cancelled",
      });
      await Promise.resolve();
    });
    await waitFor(() => expect(hook.result.current.cancelImportMutation.isSuccess).toBe(true));
    expect(hook.setStatus).not.toHaveBeenCalled();
    expect(hook.setPollKey).not.toHaveBeenCalled();
    expect(hook.setError).not.toHaveBeenCalled();
    hook.unmount();
  });

  it("shows cancellation only for an unfinished job and disables it offline", () => {
    const onCancelImport = vi.fn();
    const active = {
      status: "IMPORTING",
      valid_rows: 10,
      imported_rows: 2,
      invalid_rows: 0,
      import_failed_rows: 0,
      default_lot_control_mode: "NONE",
      default_expiry_control_mode: "NONE",
    } as ProductImportState;
    const props = {
      status: active,
      pollError: null,
      progress: 20,
      online: true,
      retryPending: false,
      cancelPending: false,
      onCancelImport,
      onRetryPoll: vi.fn(),
      onDownloadErrorReport: vi.fn(),
      onResetImport: vi.fn(),
      onRetryImport: vi.fn(),
      onCompletedClose: vi.fn(),
    };
    const view = render(<ImportProductStatusPanel {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "products.cancelImport" }));
    expect(onCancelImport).toHaveBeenCalledTimes(1);

    view.rerender(<ImportProductStatusPanel {...props} status={null} />);
    expect(screen.getByRole("button", { name: "products.cancelImport" })).not.toBeNull();
    view.rerender(<ImportProductStatusPanel {...props} status={null} online={false} />);
    expect((screen.getByRole("button", { name: "products.cancelImport" }) as HTMLButtonElement).disabled).toBe(true);

    view.rerender(<ImportProductStatusPanel {...props} online={false} />);
    expect((screen.getByRole("button", { name: "products.cancelImport" }) as HTMLButtonElement).disabled).toBe(true);

    view.rerender(<ImportProductStatusPanel {...props} status={{
      ...active, status: "COMPLETED",
    }} />);
    expect(screen.queryByRole("button", { name: "products.cancelImport" })).toBeNull();
  });
});

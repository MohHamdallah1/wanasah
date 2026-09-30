import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportRejectedRowsReview } from "@/pages/products/import/ImportRejectedRowsReview";

vi.mock("react-i18next", async (importOriginal) => {
  const original = await importOriginal<typeof import("react-i18next")>();
  return {
    ...original,
    useTranslation: () => ({
      t: (key: string, data?: { row?: number; page?: number }) =>
        data?.row ? `Row ${data.row}` : data?.page ? `Page ${data.page}` : key,
      i18n: { exists: () => false },
    }),
  };
});

const JOB = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const rejection = (row_number: number) => ({
  row_number,
  code: "IMPORT_ROW_INVALID",
  message: "Safe message",
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("bounded rejected-row error review", () => {
  it("loads only on explicit opening; cursor-paginates 25 rows with real Excel row numbers", async () => {
    const firstPage = {
      items: Array.from({ length: 25 }, (_v, i) => rejection(i + 2)),
      next_after_row: 26,
    };
    const lastPage = {
      items: [rejection(27), rejection(31)],
      next_after_row: null,
    };
    const authFetch = vi.fn()
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(lastPage)
      .mockResolvedValueOnce(firstPage);
    render(<ImportRejectedRowsReview jobId={JOB} online authFetch={authFetch} />);
    expect(authFetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /products.rejectedRows.show/ }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(25));
    expect(authFetch).toHaveBeenCalledWith(
      `/simple-products/imports/${JOB}/errors?after_row=0&limit=25`,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(screen.getByText("Row 26")).not.toBeNull();
    expect(screen.queryByText("Row 27")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /products.rejectedRows.next/ }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    expect(screen.getByText("Row 31")).not.toBeNull();
    expect(authFetch).toHaveBeenNthCalledWith(
      2,
      `/simple-products/imports/${JOB}/errors?after_row=26&limit=25`,
      expect.any(Object),
    );
    expect((screen.getByRole("button", { name: /products.rejectedRows.next/ }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /products.rejectedRows.previous/ }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(25));
    expect(screen.getByText("Page 1")).not.toBeNull();
    expect(authFetch).toHaveBeenCalledTimes(3);
  });

  it("rejects server cursors that do not advance and offers a bounded retry, never loops", async () => {
    const authFetch = vi.fn()
      .mockResolvedValueOnce({ items: [rejection(2)], next_after_row: 2 })
      .mockResolvedValueOnce({ items: [rejection(5)], next_after_row: 3 })
      .mockResolvedValueOnce({ items: [rejection(5)], next_after_row: null });
    render(<ImportRejectedRowsReview jobId={JOB} online authFetch={authFetch} />);
    fireEvent.click(screen.getByRole("button", { name: /products.rejectedRows.show/ }));
    await waitFor(() => expect(screen.getByText("Row 2")).not.toBeNull());
    fireEvent.click(screen.getByRole("button", { name: /products.rejectedRows.next/ }));
    await waitFor(() => expect(screen.getByRole("alert")).not.toBeNull());
    expect(screen.queryByText("Row 5")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    await waitFor(() => expect(screen.getByText("Row 5")).not.toBeNull());
    expect(authFetch).toHaveBeenCalledTimes(3);
  });

  it("ignores an old job response after a scoped review is replaced by another job", async () => {
    let finishOld!: (value: unknown) => void;
    const old = new Promise<unknown>((resolve) => { finishOld = resolve; });
    const authFetch = vi.fn()
      .mockReturnValueOnce(old)
      .mockResolvedValueOnce({ items: [rejection(98)], next_after_row: null });

    const view = render(<ImportRejectedRowsReview key={JOB} jobId={JOB} online authFetch={authFetch} />);
    fireEvent.click(screen.getByRole("button", { name: /products.rejectedRows.show/ }));
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(1));
    view.rerender(<ImportRejectedRowsReview key={OTHER} jobId={OTHER} online authFetch={authFetch} />);
    fireEvent.click(screen.getByRole("button", { name: /products.rejectedRows.show/ }));
    await waitFor(() => expect(screen.getByText("Row 98")).not.toBeNull());
    finishOld({ items: [rejection(9)], next_after_row: null });
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    expect(screen.queryByText("Row 9")).toBeNull();
    expect(authFetch).toHaveBeenNthCalledWith(
      2,
      `/simple-products/imports/${OTHER}/errors?after_row=0&limit=25`,
      expect.any(Object),
    );
  });
});

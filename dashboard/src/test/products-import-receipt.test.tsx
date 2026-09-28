import {
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import {
  afterEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  readFileSync,
} from "node:fs";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (
      key: string,
      options?: { count?: number },
    ) =>
      options?.count === undefined
        ? key
        : key + ":" + options.count,
  }),
}));

import {
  ProductImportReceiptBanner,
} from "@/pages/products/import/ProductImportReceiptBanner";

const read = (path: string) =>
  readFileSync(
    new URL(path, import.meta.url),
    "utf8",
  );

afterEach(() => cleanup());

describe("Product Import durable completion feedback", () => {
  it("separates saved products from rows not imported and permits clearing filters", () => {
    const onClearFilters = vi.fn();
    const onDismiss = vi.fn();

    render(
      <ProductImportReceiptBanner
        imported={38}
        needsReview={16}
        hasFilters={true}
        onClearFilters={onClearFilters}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "products.importReceipt.saved:38",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "products.importReceipt.needsReview:16",
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: "products.importReceipt.clearFilters",
      }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "products.importReceipt.dismiss",
      }),
    );
    expect(onClearFilters).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("does not claim rejected rows for a fully successful import", () => {
    render(
      <ProductImportReceiptBanner
        imported={54}
        needsReview={0}
        hasFilters={false}
        onClearFilters={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "products.importReceipt.saved:54",
    );
    expect(screen.getByRole("status")).not.toHaveTextContent(
      "products.importReceipt.needsReview",
    );
    expect(
      screen.queryByRole("button", {
        name: "products.importReceipt.clearFilters",
      }),
    ).not.toBeInTheDocument();
  });

  it("records the completed status before resetting the modal and scopes the receipt to its company", () => {
    const page = read(
      "../pages/products/ProductsPage.tsx",
    );
    const panel = read(
      "../pages/products/import/ImportProductStatusPanel.tsx",
    );

    expect(page).toContain(
      "lastImportReceipt?.companyId === companyId",
    );
    expect(page).toContain(
      "rememberCompletedImport(importWorkflow.modalProps.status)",
    );
    expect(page).toContain(
      "importWorkflow.modalProps.onCompletedClose();",
    );
    expect(page).toContain(
      "listWorkflow.section.results.onClearCriteria",
    );
    expect(panel).toContain(
      '"products.importReceipt.saved"',
    );
    expect(panel).toContain(
      '"products.importReceipt.needsReview"',
    );
  });
});

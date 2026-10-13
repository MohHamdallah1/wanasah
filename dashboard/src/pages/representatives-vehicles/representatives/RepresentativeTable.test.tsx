import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { limit?: string }) =>
      key.endsWith("creditAllowed") ? `credit:${options?.limit}` : key,
    i18n: { dir: () => "rtl" },
  }),
}));

import { RepresentativeTable } from "./RepresentativeTable";

const allowed = {
  id: 1, full_name: "Ahmad", username: "rep-1", phone_number: "+962790000001",
  is_active: true, can_allow_debt: true, max_debt_limit: "50000.000",
};
const denied = {
  id: 2, full_name: "Salem", username: "rep-2", phone_number: null,
  is_active: true, can_allow_debt: false, max_debt_limit: "25.500",
};

afterEach(cleanup);

describe("RepresentativeTable", () => {
  it("uses one explicit six-column geometry for header and rows", () => {
    const { container } = render(<RepresentativeTable items={[allowed]} onOpen={() => undefined} />);
    const table = container.querySelector("table")!;
    expect(table.className).toContain("table-fixed");
    expect(table.querySelectorAll("colgroup col")).toHaveLength(6);
    expect(table.querySelectorAll("thead th")).toHaveLength(6);
    expect(table.querySelectorAll("tbody tr:first-child td")).toHaveLength(6);

    const cells = table.querySelectorAll("tbody tr:first-child td");
    expect(cells[0]?.textContent).toBe("Ahmad");
    expect(cells[1]?.textContent).toBe("rep-1");
    expect(cells[2]?.textContent).toBe("+962790000001");
    expect(cells[3]?.textContent).toBe("credit:50,000.000");
    expect(cells[1]?.querySelector("bdi")?.getAttribute("dir")).toBe("ltr");
    expect(cells[2]?.querySelector("bdi")?.getAttribute("dir")).toBe("ltr");
  });

  it("shows disabled credit authority explicitly without implying the stored limit is usable", () => {
    render(<RepresentativeTable items={[denied]} onOpen={() => undefined} />);
    expect(screen.getByText("representativesVehicles.representatives.fields.creditDisabled")).toBeTruthy();
    expect(screen.queryByText(/25\.500/)).toBeNull();
  });
});

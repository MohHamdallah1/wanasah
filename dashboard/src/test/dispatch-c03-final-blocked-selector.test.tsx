import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { LaunchResourceSelect } from "../features/dispatch/launchResources/LaunchResourceSelect";
import type { LaunchOption } from "../features/dispatch/launchResources/launchResourceRead";

vi.mock("react-i18next", async (importOriginal) => ({
  ...await importOriginal<typeof import("react-i18next")>(),
  useTranslation: () => ({
    i18n: { language: "en", resolvedLanguage: "en", dir: () => "ltr" },
  }),
}));

const rows: LaunchOption[] = [
  { id: "17", label: "Truck stock with no proof", available: false,
    code: "CUSTODY_STOCK_WITHOUT_EPOCH" },
  { id: "18", label: "Truck under maintenance", available: false,
    code: "VEHICLE_NOT_OPERATIONAL" },
  { id: "19", label: "Already accepted car", available: true,
    code: "AVAILABLE" },
];
function Selector({ canReview, review }: {
  canReview: boolean; review: (value: LaunchOption) => void;
}) {
  const [selected, setSelected] = useState("");
  return <>
    <LaunchResourceSelect
      kind="vehicles" label="Vehicle" options={rows}
      value={selected} onChange={setSelected}
      disabled={false} placeholder="Choose a vehicle"
      onBlockedVehicleReview={canReview ? review : undefined}
    />
    <output data-testid="selected-launch-car">{selected}</output>
  </>;
}
describe("C03 actual resource selector", () => {
  it("lets an authorized manager enter recovery for an UNSELECTABLE car", () => {
    const review = vi.fn();
    render(<Selector canReview review={review} />);
    fireEvent.click(screen.getByRole("button", {name: "Choose a vehicle"}));
    const blocked = screen.getByRole("option",{name:"Truck stock with no proof"});
    expect(blocked).toHaveProperty("disabled", true);
    expect(screen.getByText("Vehicle holds stock without a trusted custody record; investigate before launch"))
      .toBeTruthy();
    expect(screen.getByTestId("selected-launch-car").textContent).toBe("");
    fireEvent.click(screen.getByTestId("c03-review-blocked-car-17"));
    expect(review).toHaveBeenCalledTimes(1);
    expect(review.mock.calls[0][0]).toEqual(rows[0]);
    expect(screen.getByTestId("selected-launch-car").textContent).toBe("");
    expect(screen.queryByRole("listbox")).toBeNull();
  });
  it("never shows recovery for ordinary blockers or to the limited role", () => {
    const review = vi.fn();
    const {rerender} = render(<Selector canReview review={review} />);
    fireEvent.click(screen.getByRole("button", {name:"Choose a vehicle"}));
    expect(screen.queryByTestId("c03-review-blocked-car-18")).toBeNull();
    rerender(<Selector canReview={false} review={review} />);
    expect(screen.queryByTestId("c03-review-blocked-car-17")).toBeNull();
    expect(screen.getByRole("option",{name:"Truck stock with no proof"}))
      .toHaveProperty("disabled",true);
    expect(review).not.toHaveBeenCalled();
  });
  it("selects only genuinely available car through original route code",()=>{
    const review=vi.fn();
    render(<Selector canReview review={review}/>);
    fireEvent.click(screen.getByRole("button",{name:"Choose a vehicle"}));
    fireEvent.click(screen.getByRole("option",{name:"Already accepted car"}));
    expect(screen.getByTestId("selected-launch-car").textContent).toBe("19");
    expect(review).not.toHaveBeenCalled();
  });
});

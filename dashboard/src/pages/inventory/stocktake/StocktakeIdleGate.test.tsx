import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StocktakeIdlePanel } from "./StocktakeIdlePanel";

vi.mock("./uiCopy", () => ({
  useStocktakeUiCopy: () => ({
    copy: {
      idle: {
        title: "Stocktake",
        body: "Count the current warehouse",
        start: "Start",
        startLabel: "Start a full stocktake",
        blindHint: "Verified only",
      },
    },
  }),
}));

describe("Stocktake immediate shell and signed start fence", () => {
  it("keeps the start surface mounted and rejects clicks until the current warehouse read is verified", () => {
    const onStart = vi.fn();
    const view = render(<StocktakeIdlePanel onStart={onStart} disabled />);
    const button = screen.getByRole("button", { name: "Start a full stocktake" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onStart).not.toHaveBeenCalled();
    view.rerender(<StocktakeIdlePanel onStart={onStart} disabled={false} />);
    expect(screen.getByRole("button", { name: "Start a full stocktake" })).toBe(button);
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onStart).toHaveBeenCalledOnce();
  });
});

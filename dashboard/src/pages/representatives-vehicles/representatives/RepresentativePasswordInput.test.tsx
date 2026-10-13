import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { RepresentativePasswordInput } from "./RepresentativePasswordInput";

function Harness({ resetSignal = 1 }: { resetSignal?: unknown }) {
  let value = "password8";
  return (
    <RepresentativePasswordInput
      id="password"
      value={value}
      onChange={(next) => { value = next; }}
      className="input"
      resetSignal={resetSignal}
    />
  );
}

describe("RepresentativePasswordInput", () => {
  it("shows an application-owned toggle only when a value exists", () => {
    const { rerender } = render(
      <RepresentativePasswordInput id="password" value="" onChange={() => undefined} className="input" />,
    );
    expect(screen.queryByRole("button")).toBeNull();
    rerender(
      <RepresentativePasswordInput id="password" value="password8" onChange={() => undefined} className="input" />,
    );
    expect(screen.getByRole("button", { name: "representativesVehicles.representatives.passwordVisibility.show" })).toBeTruthy();
  });

  it("toggles password/text without mutating the value and survives blur", () => {
    render(<Harness />);
    const input = screen.getByRole("textbox", { hidden: true }) as HTMLInputElement;
    expect(input.type).toBe("password");
    const show = screen.getByRole("button", { name: "representativesVehicles.representatives.passwordVisibility.show" });
    fireEvent.click(show);
    expect(input.type).toBe("text");
    expect(input.value).toBe("password8");
    fireEvent.blur(input);
    expect(screen.getByRole("button", { name: "representativesVehicles.representatives.passwordVisibility.hide" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "representativesVehicles.representatives.passwordVisibility.hide" }));
    expect(input.type).toBe("password");
    expect(input.value).toBe("password8");
  });

  it("resets visibility to hidden when reset signal changes", () => {
    const { rerender } = render(<Harness resetSignal={1} />);
    const input = document.getElementById("password") as HTMLInputElement;
    fireEvent.click(screen.getByRole("button", { name: "representativesVehicles.representatives.passwordVisibility.show" }));
    expect(input.type).toBe("text");
    rerender(<Harness resetSignal={2} />);
    expect((document.getElementById("password") as HTMLInputElement).type).toBe("password");
  });
});

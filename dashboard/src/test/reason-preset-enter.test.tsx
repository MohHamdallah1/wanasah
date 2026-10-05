import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReasonPresetField } from "@/components/forms/ReasonPresetField";

function Harness({ onSubmit }: { onSubmit: () => void }) {
  const [value, setValue] = useState("");
  return (
    <ReasonPresetField
      label="سبب التغيير"
      chooseLabel="اختر سببًا"
      otherLabel="سبب آخر"
      customPlaceholder="اكتب السبب"
      presets={["مراجعة التسعير", "إيقاف إداري"]}
      value={value}
      onChange={setValue}
      maxLength={1000}
      canSubmit={value.trim().length >= 3}
      onSubmit={onSubmit}
    />
  );
}

describe("ReasonPresetField keyboard submit", () => {
  it("submits with Enter after choosing a preset reason", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);

    const select = screen.getByRole("combobox", {
      name: "سبب التغيير",
    });
    fireEvent.change(select, {
      target: { value: "مراجعة التسعير" },
    });
    fireEvent.keyDown(select, { key: "Enter" });

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});

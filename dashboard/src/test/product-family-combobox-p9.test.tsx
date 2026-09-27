import {
  useState,
} from "react";
import {
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import {
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { ProductFamilyCombobox } from "@/pages/products/family/ProductFamilyCombobox";
import type {
  ProductFamily,
} from "@/pages/products/contracts";

const options: ProductFamily[] = [
  {
    id: 7,
    name: "Chips",
    version: 1,
    variant_count: 4,
  },
  {
    id: 8,
    name: "Drinks",
    version: 1,
    variant_count: 3,
  },
];

function Harness({
  onSelect,
}: {
  onSelect: (
    family: ProductFamily,
  ) => void;
}) {
  const [
    search,
    setSearch,
  ] = useState("");

  return (
    <ProductFamilyCombobox
      selectedName=""
      searchValue={search}
      options={options}
      placeholder="Search family"
      clearLabel="Clear"
      emptyLabel="No matches"
      onSearchChange={setSearch}
      onSelect={onSelect}
      onClear={() =>
        setSearch("")
      }
      inputClassName="h-9"
    />
  );
}

describe(
  "Product family combobox keyboard contract",
  () => {
    it("does not auto-open on focus", () => {
      render(
        <Harness
          onSelect={vi.fn()}
        />,
      );

      const input =
        screen.getByRole(
          "combobox",
        );
      fireEvent.focus(input);

      expect(
        input,
      ).toHaveAttribute(
        "aria-expanded",
        "false",
      );
      expect(
        screen.queryByText(
          "Chips",
        ),
      ).not.toBeInTheDocument();
    });

    it("supports ArrowUp/ArrowDown and Enter selection", () => {
      const onSelect =
        vi.fn();
      render(
        <Harness
          onSelect={onSelect}
        />,
      );

      const input =
        screen.getByRole(
          "combobox",
        );
      fireEvent.click(input);

      expect(
        input,
      ).toHaveAttribute(
        "aria-expanded",
        "true",
      );

      fireEvent.keyDown(
        input,
        {
          key: "ArrowDown",
        },
      );
      expect(
        input.getAttribute(
          "aria-activedescendant",
        ),
      ).toBeTruthy();
      expect(
        screen.getByRole(
          "option",
          {
            name: "Chips",
          },
        ),
      ).toHaveClass(
        "bg-amber-100",
      );

      fireEvent.keyDown(
        input,
        {
          key: "Enter",
        },
      );

      expect(
        onSelect,
      ).toHaveBeenCalledTimes(
        1,
      );
      expect(
        onSelect.mock.calls[0][0].name,
      ).toBe("Chips");
      expect(
        input,
      ).toHaveAttribute(
        "aria-expanded",
        "false",
      );
    });

    it("typing keeps the same field as the search authority", () => {
      render(
        <Harness
          onSelect={vi.fn()}
        />,
      );

      const input =
        screen.getByRole(
          "combobox",
        );
      fireEvent.change(input, {
        target: {
          value: "Drink",
        },
      });

      expect(input).toHaveValue(
        "Drink",
      );
      expect(
        input,
      ).toHaveAttribute(
        "aria-expanded",
        "true",
      );
    });
  },
);

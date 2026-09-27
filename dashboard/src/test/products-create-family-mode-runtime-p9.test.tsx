import {
  createRef,
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

import { CreateProductIdentitySection } from "@/pages/products/create/CreateProductIdentitySection";
import type {
  ProductFamily,
} from "@/pages/products/contracts";
import type {
  ProductDraft,
  ProductFamilyMode,
} from "@/pages/products/create/types";
import { emptyDraft } from "@/pages/products/create/useCreateProductState";

const families: ProductFamily[] = [
  {
    id: 7,
    name: "Chips",
    version: 1,
    variant_count: 4,
  },
];

function Harness() {
  const [
    draft,
    setDraft,
  ] = useState<ProductDraft>(
    emptyDraft
  );

  const changeMode = (
    mode: ProductFamilyMode,
  ) => {
    setDraft((current) => ({
      ...current,
      family_mode: mode,
      family_id: null,
      family: "",
    }));
  };

  return (
    <CreateProductIdentitySection
      draft={draft}
      createFieldError={null}
      familyOptions={families}
      familyOptionsLoading={false}
      familyOptionsError={false}
      createNameRef={createRef<HTMLInputElement>()}
      createFamilyRef={createRef<HTMLInputElement>()}
      onNameChange={(value) =>
        setDraft((current) => ({
          ...current,
          name: value,
        }))
      }
      onFamilyModeChange={changeMode}
      onFamilyChange={(
        value,
        familyId = null,
      ) =>
        setDraft((current) => ({
          ...current,
          family: value,
          family_id: familyId,
        }))
      }
      onFamilySearchChange={vi.fn()}
      onRetryFamilyOptions={vi.fn()}
    />
  );
}

describe(
  "Products create family mode runtime",
  () => {
    it("switches existing, new, none, and back without crashing", () => {
      render(<Harness />);

      const group =
        screen.getByRole(
          "group",
          {
            name:
              "products.familyModeLabel",
          },
        );

      const buttons =
        Array.from(
          group.querySelectorAll(
            "button"
          )
        );
      expect(buttons).toHaveLength(3);

      const [
        existing,
        createNew,
        none,
      ] = buttons;

      expect(
        existing
      ).toHaveAttribute(
        "aria-pressed",
        "true"
      );
      expect(
        screen.getByRole(
          "combobox"
        )
      ).toBeInTheDocument();

      fireEvent.click(createNew);
      expect(
        createNew
      ).toHaveAttribute(
        "aria-pressed",
        "true"
      );
      expect(
        screen.queryByRole(
          "combobox"
        )
      ).not.toBeInTheDocument();

      fireEvent.click(none);
      expect(
        none
      ).toHaveAttribute(
        "aria-pressed",
        "true"
      );
      expect(
        screen.queryByRole(
          "combobox"
        )
      ).not.toBeInTheDocument();

      fireEvent.click(existing);
      expect(
        existing
      ).toHaveAttribute(
        "aria-pressed",
        "true"
      );
      expect(
        screen.getByRole(
          "combobox"
        )
      ).toBeInTheDocument();
    });
  },
);

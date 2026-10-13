import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name?: string }) => {
      if (key.endsWith("actionsMenu")) return `actions:${options?.name}`;
      if (key.endsWith("edit")) return "edit";
      if (key.endsWith("lifecycle.deactivate")) return "deactivate";
      if (key.endsWith("lifecycle.reactivate")) return "reactivate";
      if (key.endsWith("credentials.reset")) return "reset";
      if (key.endsWith("permissions.manageRequired")) return "manage-blocked";
      if (key.endsWith("permissions.credentialsRequired")) return "credentials-blocked";
      return key;
    },
    i18n: { dir: () => "rtl" },
  }),
}));

vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuSeparator: () => <hr />,
  DropdownMenuItem: ({ children, disabled, onSelect, ...props }: {
    children: ReactNode;
    disabled?: boolean;
    onSelect?: () => void;
  } & HTMLAttributes<HTMLButtonElement>) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onSelect?.()}
      {...props as ButtonHTMLAttributes<HTMLButtonElement>}
    >
      {children}
    </button>
  ),
}));

import { RepresentativeRowActions } from "./RepresentativeRowActions";

const active = {
  id: 17,
  full_name: "Ahmad Saleh",
  username: "rep17",
  phone_number: null,
  is_active: true,
  can_allow_debt: false,
  max_debt_limit: "0.000",
};

afterEach(cleanup);

describe("RepresentativeRowActions", () => {
  it("emits edit, lifecycle, and credential actions directly from the menu", () => {
    const onEdit = vi.fn();
    const onLifecycle = vi.fn();
    const onResetCredentials = vi.fn();
    render(
      <RepresentativeRowActions
        representative={active}
        canManage
        canResetCredentials
        onEdit={onEdit}
        onLifecycle={onLifecycle}
        onResetCredentials={onResetCredentials}
      />,
    );

    expect(screen.getByRole("button", { name: "actions:Ahmad Saleh" })).toBeTruthy();
    fireEvent.click(screen.getByText("edit"));
    fireEvent.click(screen.getByText("deactivate"));
    fireEvent.click(screen.getByText("reset"));
    expect(onEdit).toHaveBeenCalledWith(active);
    expect(onLifecycle).toHaveBeenCalledWith(active);
    expect(onResetCredentials).toHaveBeenCalledWith(active);
    expect(screen.queryByText(/details/i)).toBeNull();
  });

  it("switches lifecycle wording for an inactive representative", () => {
    render(
      <RepresentativeRowActions
        representative={{ ...active, is_active: false }}
        canManage
        canResetCredentials
        onEdit={vi.fn()}
        onLifecycle={vi.fn()}
        onResetCredentials={vi.fn()}
      />,
    );
    expect(screen.getByText("reactivate")).toBeTruthy();
    expect(screen.queryByText("deactivate")).toBeNull();
  });

  it("gates manage and credential actions independently", () => {
    render(
      <RepresentativeRowActions
        representative={active}
        canManage={false}
        canResetCredentials
        onEdit={vi.fn()}
        onLifecycle={vi.fn()}
        onResetCredentials={vi.fn()}
      />,
    );
    expect(screen.getByText("edit")).toBeDisabled();
    expect(screen.getByText("deactivate")).toBeDisabled();
    expect(screen.getByText("reset")).not.toBeDisabled();

    cleanup();
    render(
      <RepresentativeRowActions
        representative={active}
        canManage
        canResetCredentials={false}
        onEdit={vi.fn()}
        onLifecycle={vi.fn()}
        onResetCredentials={vi.fn()}
      />,
    );
    expect(screen.getByText("edit")).not.toBeDisabled();
    expect(screen.getByText("deactivate")).not.toBeDisabled();
    expect(screen.getByText("reset")).toBeDisabled();
  });
});

import type {
  HTMLAttributes,
  ReactNode,
} from "react";

import "./WorkspaceTopBar.css";

type WorkspaceTopBarVariant =
  | "dock"
  | "page";

type Props = Omit<
  HTMLAttributes<HTMLDivElement>,
  "children"
> & {
  children: ReactNode;
  variant?: WorkspaceTopBarVariant;
};

export function WorkspaceTopBar({
  children,
  variant = "page",
  className = "",
  ...frameProps
}: Props) {
  return (
    <div
      {...frameProps}
      className={`workspace-top-bar-frame${
        className ? ` ${className}` : ""
      }`}
    >
      <div
        className={`workspace-top-bar workspace-top-bar--${variant}`}
      >
        {children}
      </div>
    </div>
  );
}

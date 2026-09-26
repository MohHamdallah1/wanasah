import type {
  ReactNode,
} from "react";

import "./WorkspaceTopBar.css";

type WorkspaceTopBarVariant =
  | "dock"
  | "page";

type Props = {
  children: ReactNode;
  variant?: WorkspaceTopBarVariant;
  className?: string;
};

export function WorkspaceTopBar({
  children,
  variant = "page",
  className = "",
}: Props) {
  return (
    <div
      className={`workspace-top-bar workspace-top-bar--${variant}${
        className ? ` ${className}` : ""
      }`}
    >
      {children}
    </div>
  );
}

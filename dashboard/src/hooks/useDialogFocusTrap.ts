import {
  useEffect,
  useRef,
} from "react";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type=\"hidden\"])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex=\"-1\"])",
].join(",");

const focusableWithin = (
  container: HTMLElement,
): HTMLElement[] =>
  Array.from(
    container.querySelectorAll<HTMLElement>(
      FOCUSABLE_SELECTOR,
    ),
  );

type DialogInitialFocusRef = {
  readonly current: HTMLElement | null;
};

export function useDialogFocusTrap<
  T extends HTMLElement,
>(
  open: boolean,
  onClose: () => void,
  initialFocusRef?: DialogInitialFocusRef,
) {
  const containerRef =
    useRef<T | null>(null);
  const closeRef = useRef(onClose);
  const restoreFocusRef =
    useRef<HTMLElement | null>(null);

  closeRef.current = onClose;

  useEffect(() => {
    if (!open) {
      return;
    }

    const container =
      containerRef.current;
    if (!container) {
      return;
    }

    restoreFocusRef.current =
      document.activeElement instanceof
      HTMLElement
        ? document.activeElement
        : null;

    const focusInitial = () => {
      const preferred =
        initialFocusRef?.current;
      if (
        preferred &&
        container.contains(
          preferred
        ) &&
        !preferred.hasAttribute(
          "disabled"
        )
      ) {
        preferred.focus();
        return;
      }

      const first =
        focusableWithin(container)[0] ??
        container;
      first.focus();
    };

    const frame =
      window.requestAnimationFrame(
        focusInitial,
      );

    const handleKeyDown = (
      event: KeyboardEvent,
    ) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const focusable =
        focusableWithin(container);
      if (focusable.length === 0) {
        event.preventDefault();
        container.focus();
        return;
      }

      const first = focusable[0];
      const last =
        focusable[focusable.length - 1];
      const active =
        document.activeElement;

      if (
        event.shiftKey &&
        (active === first ||
          !container.contains(active))
      ) {
        event.preventDefault();
        last.focus();
        return;
      }

      if (
        !event.shiftKey &&
        active === last
      ) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener(
      "keydown",
      handleKeyDown,
    );

    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener(
        "keydown",
        handleKeyDown,
      );
      const restore =
        restoreFocusRef.current;
      restoreFocusRef.current = null;
      if (
        restore &&
        restore.isConnected
      ) {
        window.requestAnimationFrame(
          () => restore.focus(),
        );
      }
    };
  }, [
    initialFocusRef,
    open,
  ]);

  return containerRef;
}

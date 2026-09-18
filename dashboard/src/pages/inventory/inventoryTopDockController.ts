export type InventoryTopDockOptions = {
  proximity: number;
  spring: number;
  damping: number;
  widthGrowth: number;
  heightGrowth: number;
  drop: number;
  lockTrack?: boolean;
};

type DockItemState = {
  element: HTMLElement;
  baseWidth: number;
  baseHeight: number;
  value: number;
  velocity: number;
  target: number;
};

const clamp = (
  value: number,
  min: number,
  max: number,
): number => Math.max(min, Math.min(max, value));

export function createInventoryTopDockController(
  root: HTMLElement,
  getOptions: () => InventoryTopDockOptions,
) {
  const reducedQuery = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  );
  const precisionQuery = window.matchMedia(
    "(hover:hover) and (pointer:fine)",
  );

  const items: DockItemState[] = Array.from(
    root.querySelectorAll<HTMLElement>(
      "[data-inventory-dock-item]",
    ),
  ).map((element) => ({
    element,
    baseWidth: 0,
    baseHeight: 0,
    value: 0,
    velocity: 0,
    target: 0,
  }));

  let enabled = false;
  let pointerActive = false;
  let dirty = false;
  let frame = 0;

  const canAnimate = () =>
    !reducedQuery.matches &&
    root.clientWidth > 0 &&
    window.innerWidth > 600 &&
    precisionQuery.matches;

  const applyLayout = () => {
    const options = getOptions();

    for (const state of items) {
      const value = clamp(state.value, 0, 1.08);
      const extraWidth = Math.min(
        options.widthGrowth,
        state.baseWidth * 0.24,
      );

      state.element.style.width = `${
        state.baseWidth + extraWidth * value
      }px`;
      state.element.style.height = `${
        state.baseHeight + options.heightGrowth * value
      }px`;
      state.element.style.transform =
        `translateY(${(value * options.drop).toFixed(2)}px)`;
    }
  };

  const measure = () => {
    enabled = canAnimate();

    if (getOptions().lockTrack) {
      root.style.width = "";
    }

    for (const state of items) {
      state.element.style.width = "";
      state.element.style.height = "";
      state.element.style.transform = "";
      state.element.dataset.dockNear = "false";
    }

    for (const state of items) {
      const rect = state.element.getBoundingClientRect();
      state.baseWidth = rect.width;
      state.baseHeight = rect.height;
      state.value = 0;
      state.velocity = 0;
      state.target = 0;
    }

    pointerActive = false;
    dirty = false;

    if (getOptions().lockTrack) {
      root.style.width = `${
        root.getBoundingClientRect().width.toFixed(2)
      }px`;
    }

    root.dataset.dockState = enabled ? "idle" : "static";
    root.dataset.dockMax = "0.00";
  };

  const draw = () => {
    frame = 0;

    if (!enabled || !dirty) return;

    const options = getOptions();
    let moving = false;
    let maxValue = 0;

    for (const state of items) {
      state.velocity +=
        (state.target - state.value) * options.spring;
      state.velocity *= options.damping;
      state.value += state.velocity;

      if (
        Math.abs(state.target - state.value) < 0.001 &&
        Math.abs(state.velocity) < 0.001
      ) {
        state.value = state.target;
        state.velocity = 0;
      } else {
        moving = true;
      }

      maxValue = Math.max(
        maxValue,
        clamp(state.value, 0, 1.08),
      );
    }

    applyLayout();
    root.dataset.dockMax = maxValue.toFixed(2);

    if (!moving) {
      dirty = false;
      if (
        items.every((state) => state.target === 0)
      ) {
        root.dataset.dockState = "idle";
      }
      return;
    }

    frame = requestAnimationFrame(draw);
  };

  const ensureFrame = () => {
    if (enabled && dirty && !frame) {
      frame = requestAnimationFrame(draw);
    }
  };

  const setTargets = (
    clientX: number,
    clientY: number,
  ) => {
    if (!enabled) return;

    const options = getOptions();
    const pointer = clientX;
    const rects = items.map((state) =>
      state.element.getBoundingClientRect(),
    );

    for (let index = 0; index < items.length; index += 1) {
      const rect = rects[index];
      const center = rect.left + rect.width * 0.5;
      const proximity = clamp(
        1 -
          Math.abs(pointer - center) /
            Math.max(1, options.proximity),
        0,
        1,
      );
      const influence =
        proximity * proximity * (3 - 2 * proximity);

      items[index].target = influence;
      items[index].element.dataset.dockNear =
        influence > 0.08 ? "true" : "false";
    }

    pointerActive = true;
    dirty = true;
    root.dataset.dockState = "active";
    ensureFrame();

    void clientY;
  };

  const focusItem = (item: HTMLElement) => {
    if (!enabled) return;

    const index = items.findIndex(
      (state) => state.element === item,
    );
    if (index < 0) return;

    items.forEach((state, itemIndex) => {
      state.target =
        itemIndex === index
          ? 1
          : Math.abs(itemIndex - index) === 1
            ? 0.24
            : 0;
      state.element.dataset.dockNear =
        state.target > 0.08 ? "true" : "false";
    });

    pointerActive = false;
    dirty = true;
    root.dataset.dockState = "focus";
    ensureFrame();
  };

  const reset = () => {
    pointerActive = false;
    dirty = true;
    items.forEach((state) => {
      state.target = 0;
      state.element.dataset.dockNear = "false";
    });
    ensureFrame();
  };

  const resetImmediate = () => {
    pointerActive = false;
    dirty = false;

    if (frame) {
      cancelAnimationFrame(frame);
      frame = 0;
    }

    items.forEach((state) => {
      state.value = 0;
      state.velocity = 0;
      state.target = 0;
      state.element.style.width = "";
      state.element.style.height = "";
      state.element.style.transform = "";
      state.element.dataset.dockNear = "false";
    });

    root.dataset.dockState = enabled ? "idle" : "static";
    root.dataset.dockMax = "0.00";
  };

  const onPointerMove = (event: PointerEvent) =>
    setTargets(event.clientX, event.clientY);

  const onWindowPointerMove = (event: PointerEvent) => {
    if (!pointerActive) return;

    const rootRect = root.getBoundingClientRect();
    const itemRects = items.map((state) =>
      state.element.getBoundingClientRect(),
    );
    const bottom = Math.max(
      rootRect.bottom,
      ...itemRects.map((rect) => rect.bottom),
    );

    const outside =
      event.clientX < rootRect.left ||
      event.clientX > rootRect.right ||
      event.clientY < rootRect.top ||
      event.clientY > bottom;

    if (outside) reset();
  };

  const onFocusIn = (event: FocusEvent) => {
    const item = (
      event.target as HTMLElement | null
    )?.closest<HTMLElement>(
      "[data-inventory-dock-item]",
    );
    if (item) focusItem(item);
  };

  const onFocusOut = () =>
    requestAnimationFrame(() => {
      if (!root.contains(document.activeElement)) {
        reset();
      }
    });

  const onKeyDown = (event: KeyboardEvent) => {
    const item = (
      event.target as HTMLElement | null
    )?.closest<HTMLElement>(
      "[data-inventory-dock-item]",
    );

    if (
      item &&
      (event.key === "Enter" || event.key === " ")
    ) {
      event.preventDefault();
      item.click();
    }
  };

  const onClick = (event: MouseEvent) => {
    resetImmediate();

    // Pointer clicks must not leave the selected tab geometrically enlarged.
    // Keyboard activation keeps focus so the dock remains accessible.
    if (event.detail > 0) {
      (
        event.target as HTMLElement | null
      )?.closest<HTMLElement>(
        "[data-inventory-dock-item]",
      )?.blur();
    }
  };

  const onVisibilityChange = () => {
    if (document.hidden) {
      resetImmediate();
      return;
    }
    measure();
  };

  const onPageHide = () => resetImmediate();
  const onPageShow = () => measure();
  const onWindowBlur = () => resetImmediate();

  let released = false;
  const remeasure = () => {
    if (!released) measure();
  };
  document.fonts?.ready.then(remeasure);

  const resizeObserver = new ResizeObserver(measure);
  resizeObserver.observe(
    root.closest<HTMLElement>("[data-dock-frame]") ??
      root.parentElement ??
      root,
  );

  root.addEventListener("pointermove", onPointerMove);
  root.addEventListener("pointerleave", reset);
  root.addEventListener("focusin", onFocusIn);
  root.addEventListener("focusout", onFocusOut);
  root.addEventListener("keydown", onKeyDown);
  root.addEventListener("click", onClick);
  window.addEventListener(
    "pointermove",
    onWindowPointerMove,
    { passive: true },
  );
  window.addEventListener("blur", onWindowBlur);
  window.addEventListener("pagehide", onPageHide);
  window.addEventListener("pageshow", onPageShow);
  document.addEventListener(
    "visibilitychange",
    onVisibilityChange,
  );
  reducedQuery.addEventListener("change", measure);
  precisionQuery.addEventListener("change", measure);

  measure();

  return () => {
    released = true;
    root.style.width = "";

    if (frame) {
      cancelAnimationFrame(frame);
    }

    resizeObserver.disconnect();
    root.removeEventListener(
      "pointermove",
      onPointerMove,
    );
    root.removeEventListener("pointerleave", reset);
    root.removeEventListener("focusin", onFocusIn);
    root.removeEventListener("focusout", onFocusOut);
    root.removeEventListener("keydown", onKeyDown);
    root.removeEventListener("click", onClick);
    window.removeEventListener(
      "pointermove",
      onWindowPointerMove,
    );
    window.removeEventListener("blur", onWindowBlur);
    window.removeEventListener("pagehide", onPageHide);
    window.removeEventListener("pageshow", onPageShow);
    document.removeEventListener(
      "visibilitychange",
      onVisibilityChange,
    );
    reducedQuery.removeEventListener(
      "change",
      measure,
    );
    precisionQuery.removeEventListener(
      "change",
      measure,
    );
  };
}

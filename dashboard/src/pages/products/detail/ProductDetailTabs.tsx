import {
  useRef,
} from "react";
import { useTranslation } from "react-i18next";

export type ProductDetailTabKey =
  | "overview"
  | "package"
  | "tracking"
  | "barcodes"
  | "pricing";

type Props = {
  tabs: ProductDetailTabKey[];
  activeTab: ProductDetailTabKey;
  onChange: (
    tab: ProductDetailTabKey,
  ) => void;
};

export function ProductDetailTabs({
  tabs,
  activeTab,
  onChange,
}: Props) {
  const { t, i18n } =
    useTranslation();
  const buttonRefs =
    useRef<
      Array<HTMLButtonElement | null>
    >([]);

  const moveFocus = (
    currentIndex: number,
    direction: -1 | 1,
  ) => {
    const nextIndex =
      (currentIndex +
        direction +
        tabs.length) %
      tabs.length;
    const nextTab =
      tabs[nextIndex];

    onChange(nextTab);
    buttonRefs.current[
      nextIndex
    ]?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label={t(
        "products.details.tabs.label",
      )}
      className="shrink-0 border-b border-slate-200 bg-white px-2 sm:px-3"
    >
      <div className="flex min-w-0 items-stretch">
        {tabs.map(
          (tab, index) => {
            const selected =
              tab === activeTab;

            return (
              <button
                key={tab}
                ref={(node) => {
                  buttonRefs.current[
                    index
                  ] = node;
                }}
                type="button"
                role="tab"
                id={`product-detail-tab-${tab}`}
                aria-selected={
                  selected
                }
                aria-controls={`product-detail-panel-${tab}`}
                tabIndex={
                  selected
                    ? 0
                    : -1
                }
                onClick={() =>
                  onChange(tab)
                }
                onKeyDown={(
                  event,
                ) => {
                  const rtl =
                    i18n.dir() ===
                    "rtl";

                  if (
                    event.key ===
                    "Home"
                  ) {
                    event.preventDefault();
                    onChange(
                      tabs[0],
                    );
                    buttonRefs.current[
                      0
                    ]?.focus();
                    return;
                  }

                  if (
                    event.key ===
                    "End"
                  ) {
                    event.preventDefault();
                    const last =
                      tabs.length -
                      1;
                    onChange(
                      tabs[last],
                    );
                    buttonRefs.current[
                      last
                    ]?.focus();
                    return;
                  }

                  if (
                    event.key ===
                    "ArrowRight"
                  ) {
                    event.preventDefault();
                    moveFocus(
                      index,
                      rtl
                        ? -1
                        : 1,
                    );
                  }

                  if (
                    event.key ===
                    "ArrowLeft"
                  ) {
                    event.preventDefault();
                    moveFocus(
                      index,
                      rtl
                        ? 1
                        : -1,
                    );
                  }
                }}
                className={
                  "relative flex min-h-11 min-w-0 flex-1 items-center justify-center px-1.5 py-2 text-center text-[10px] font-black leading-4 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400 sm:px-2 sm:text-[11px] " +
                  (
                    selected
                      ? "text-slate-950"
                      : "text-slate-400 hover:text-slate-700"
                  )
                }
              >
                <span className="min-w-0 break-words">
                  {t(
                    `products.details.tabs.${tab}`,
                  )}
                </span>
                {selected ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-amber-400"
                  />
                ) : null}
              </button>
            );
          },
        )}
      </div>
    </div>
  );
}

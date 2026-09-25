import type {
  ComponentProps,
} from "react";

import { ProductTrackingEditor } from "@/pages/products/tracking/ProductTrackingEditor";
import { ProductTrackingSettings } from "@/pages/products/tracking/ProductTrackingSettings";

type Props = {
  settings:
    | ComponentProps<
        typeof ProductTrackingSettings
      >
    | null;
  editor:
    | ComponentProps<
        typeof ProductTrackingEditor
      >
    | null;
};

export function ProductTrackingOverlays({
  settings,
  editor,
}: Props) {
  return (
    <>
      {settings ? (
        <ProductTrackingSettings
          {...settings}
        />
      ) : null}

      {editor ? (
        <ProductTrackingEditor
          {...editor}
        />
      ) : null}
    </>
  );
}

import { Fragment } from "react";

type Props = { text: string; direction: "rtl" | "ltr" };

/** Render canonical formatted quantities as isolated number/UOM pairs. */
export function CommercialQuantityDisplay({ text, direction }: Props) {
  const rawParts = text.split(" + ");
  const parts = rawParts.map((part) => {
    const match = /^(-?\d+(?:\.\d{1,6})?) (.+)$/.exec(part);
    return match ? { number: match[1], unit: match[2] } : null;
  });
  // An unknown format is rendered verbatim; business quantity is never changed.
  if (parts.length > 2 || parts.some((part) => part === null)) {
    return <bdi dir={direction}>{text}</bdi>;
  }
  return (
    <span dir={direction}
      className="inline-flex max-w-full flex-nowrap items-baseline justify-center gap-x-1 whitespace-nowrap align-baseline"
      data-commercial-quantity="true">
      {parts.map((part, index) => (
        <Fragment key={index}>
          {index > 0 ? <span dir="ltr" className="shrink-0" data-quantity-join="true">+</span> : null}
          <span dir={direction}
            className="inline-flex shrink-0 flex-nowrap items-baseline gap-x-0.5"
            data-quantity-part={index}>
            <bdi dir="ltr" className="tabular-nums" data-quantity-number="true">{part!.number}</bdi>
            <bdi dir={direction} data-quantity-unit="true">{part!.unit}</bdi>
          </span>
        </Fragment>
      ))}
    </span>
  );
}

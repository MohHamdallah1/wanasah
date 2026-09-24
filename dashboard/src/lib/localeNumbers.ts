import { resolveAppLocale } from "@/lib/locale";

const localeDigitMap = (
  locale: string,
): string[] => {
  const formatter =
    new Intl.NumberFormat(resolvedLocale, {
      useGrouping: false,
      maximumFractionDigits: 0,
    });
  return Array.from(
    { length: 10 },
    (_, value) =>
      formatter.format(value),
  );
};

const decimalSeparator = (
  locale: string,
): string =>
  new Intl.NumberFormat(resolvedLocale, {
    useGrouping: false,
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })
    .formatToParts(1.1)
    .find(
      (part) =>
        part.type === "decimal",
    )?.value ?? ".";

const localizeFraction = (
  value: string,
  locale: string,
): string => {
  const digits =
    localeDigitMap(locale);
  return Array.from(value)
    .map((char) => {
      const digit = Number(char);
      return Number.isInteger(digit)
        ? digits[digit]
        : char;
    })
    .join("");
};

export const formatLocaleDecimal = (
  value: string,
  locale: string,
  minimumFractionDigits = 0,
  maximumFractionDigits = 6,
): string => {
  const resolvedLocale =
    resolveAppLocale(locale);
  const raw = value.trim();
  const match =
    /^(-?)(\d+)(?:\.(\d+))?$/.exec(
      raw,
    );
  if (!match) {
    return raw;
  }

  const minFraction = Math.max(
    0,
    Math.trunc(
      minimumFractionDigits,
    ),
  );
  const maxFraction = Math.max(
    minFraction,
    Math.trunc(
      maximumFractionDigits,
    ),
  );

  const sign =
    match[1] === "-" ? -1n : 1n;
  const integer =
    BigInt(match[2]) * sign;
  let fraction =
    (match[3] ?? "").slice(
      0,
      maxFraction,
    );

  while (
    fraction.length >
      minFraction &&
    fraction.endsWith("0")
  ) {
    fraction = fraction.slice(
      0,
      -1,
    );
  }
  fraction = fraction.padEnd(
    minFraction,
    "0",
  );

  const integerText =
    new Intl.NumberFormat(resolvedLocale, {
      useGrouping: true,
      maximumFractionDigits: 0,
    }).format(integer);

  if (!fraction) {
    return integerText;
  }

  return (
    integerText +
    decimalSeparator(resolvedLocale) +
    localizeFraction(
      fraction,
      resolvedLocale,
    )
  );
};

export const formatLocaleMoney = (
  value: string | null,
  currencyCode: string,
  locale: string,
): string => {
  if (value === null) {
    return "—";
  }
  return (
    formatLocaleDecimal(
      value,
      locale,
      3,
      6,
    ) +
    " " +
    currencyCode
  );
};

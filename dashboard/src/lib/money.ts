import { resolveAppLocale } from "@/lib/locale";

const MONEY_PATTERN = /^\d+(?:\.\d{1,6})?$/;

const canonicalMoney = (value: string): string => {
  if (!MONEY_PATTERN.test(value)) {
    throw new Error("MONEY_FORMAT_INVALID");
  }

  const [wholeRaw, fractionRaw = ""] = value.split(".");
  const whole = wholeRaw.replace(/^0+(?=\d)/, "") || "0";
  const fraction = fractionRaw.replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole;
};

const decimalSeparator = (locale: string): string => {
  try {
    return (
      new Intl.NumberFormat(locale, {
        numberingSystem: "latn",
        useGrouping: false,
      })
        .formatToParts(1.1)
        .find((part) => part.type === "decimal")?.value || "."
    );
  } catch {
    return ".";
  }
};

const formatLocalizedCurrencyAmount = (
  amount: string,
  currencyCode: string,
  locale: string,
): string => {
  const currency = currencyCode.trim().toUpperCase();
  const resolvedLocale =
    resolveAppLocale(locale);
  const localizedAmount = amount.replace(
    ".",
    decimalSeparator(resolvedLocale),
  );

  if (!/^[A-Z]{3}$/.test(currency)) {
    return currency
      ? `${localizedAmount} ${currency}`
      : localizedAmount;
  }

  try {
    const parts = new Intl.NumberFormat(resolvedLocale, {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      numberingSystem: "latn",
      useGrouping: false,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).formatToParts(0);

    const currencyIndex = parts.findIndex(
      (part) => part.type === "currency",
    );
    const integerIndex = parts.findIndex(
      (part) => part.type === "integer",
    );
    const currencyPart =
      parts[currencyIndex]?.value || currency;

    if (currencyIndex < 0 || integerIndex < 0) {
      return `${localizedAmount} ${currency}`;
    }

    const start = Math.min(currencyIndex, integerIndex) + 1;
    const end = Math.max(currencyIndex, integerIndex);
    const between =
      parts
        .slice(start, end)
        .filter((part) => part.type === "literal")
        .map((part) => part.value)
        .join("") || " ";

    return currencyIndex < integerIndex
      ? `${currencyPart}${between}${localizedAmount}`
      : `${localizedAmount}${between}${currencyPart}`;
  } catch {
    return `${localizedAmount} ${currency}`;
  }
};

const currencyDisplayFractionDigits = (
  currencyCode: string,
  locale: string,
): number => {
  const currency = currencyCode.trim().toUpperCase();
  if (!/^[A-Z]{3}$/.test(currency)) return 2;

  try {
    const resolvedLocale =
      resolveAppLocale(locale);
    return new Intl.NumberFormat(
      resolvedLocale,
      {
        style: "currency",
        currency,
        numberingSystem: "latn",
      },
    ).resolvedOptions()
      .maximumFractionDigits;
  } catch {
    return 2;
  }
};

const roundMoneyForDisplay = (
  value: string,
  fractionDigits: number,
): string => {
  const amount = canonicalMoney(value);
  const [whole, fraction = ""] = amount.split(".");
  const digits = Math.max(0, Math.min(6, fractionDigits));

  if (digits === 0) {
    const shouldRoundUp =
      (fraction[0] ?? "0") >= "5";
    return (
      BigInt(whole) + (shouldRoundUp ? 1n : 0n)
    ).toString();
  }

  const padded = fraction.padEnd(digits + 1, "0");
  const kept = padded.slice(0, digits);
  const shouldRoundUp =
    (padded[digits] ?? "0") >= "5";
  const scale = 10n ** BigInt(digits);

  let scaled =
    BigInt(whole) * scale + BigInt(kept || "0");
  if (shouldRoundUp) scaled += 1n;

  const raw = scaled
    .toString()
    .padStart(digits + 1, "0");
  const roundedWhole =
    raw.slice(0, -digits) || "0";
  const roundedFraction = raw.slice(-digits);

  if (/^0+$/.test(roundedFraction)) {
    return roundedWhole;
  }

  return `${roundedWhole}.${roundedFraction}`;
};

export function formatMoneyExact(
  value: string,
  currencyCode: string,
  locale: string,
): string {
  return formatLocalizedCurrencyAmount(
    canonicalMoney(value),
    currencyCode,
    locale,
  );
}

export function formatMoneyDisplay(
  value: string,
  currencyCode: string,
  locale: string,
): string {
  const rounded = roundMoneyForDisplay(
    value,
    currencyDisplayFractionDigits(
      currencyCode,
      locale,
    ),
  );

  return formatLocalizedCurrencyAmount(
    rounded,
    currencyCode,
    locale,
  );
}

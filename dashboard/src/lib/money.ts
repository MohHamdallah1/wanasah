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

export function formatMoneyExact(
  value: string,
  currencyCode: string,
  locale: string,
): string {
  const amount = canonicalMoney(value);
  const currency = currencyCode.trim().toUpperCase();
  const resolvedLocale = locale.trim() || "en";
  const localizedAmount = amount.replace(".", decimalSeparator(resolvedLocale));

  if (!/^[A-Z]{3}$/.test(currency)) {
    return currency ? `${localizedAmount} ${currency}` : localizedAmount;
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

    const currencyIndex = parts.findIndex((part) => part.type === "currency");
    const integerIndex = parts.findIndex((part) => part.type === "integer");
    const currencyPart = parts[currencyIndex]?.value || currency;

    if (currencyIndex < 0 || integerIndex < 0) {
      return `${localizedAmount} ${currency}`;
    }

    const start = Math.min(currencyIndex, integerIndex) + 1;
    const end = Math.max(currencyIndex, integerIndex);
    const between = parts
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
}

interface RepresentativeMoneyOptions {
  currencyLabel?: string;
  groupThousands?: boolean;
}

const EXACT_DECIMAL = /^(\d+)(?:\.(\d+))?$/;

export function formatRepresentativeMoney(
  value: string,
  options: RepresentativeMoneyOptions = {},
): string {
  const raw = value.trim();
  const match = EXACT_DECIMAL.exec(raw);
  if (!match) return raw;

  const whole = options.groupThousands === false
    ? match[1]
    : match[1].replace(/\B(?=(\d{3})+(?!\d))/g, ",");

  let fraction = (match[2] ?? "").slice(0, 3);
  while (fraction.endsWith("0")) fraction = fraction.slice(0, -1);

  const amount = fraction ? `${whole}.${fraction}` : whole;
  const currencyLabel = options.currencyLabel?.trim();
  return currencyLabel ? `${amount} ${currencyLabel}` : amount;
}

const MONEY_SCALE_FACTOR = 1_000_000n;
const MONEY_MAX_SCALED =
  99_999_999_999_999_999_999n;
const MONEY_INPUT =
  /^\+?(?:\d+(?:\.\d*)?|\.\d+)$/;

const formatScaledMoney = (
  scaled: bigint,
): string => {
  const whole =
    scaled / MONEY_SCALE_FACTOR;
  const fraction = (
    scaled % MONEY_SCALE_FACTOR
  )
    .toString()
    .padStart(6, "0");
  return `${whole}.${fraction}`;
};

const parsePositiveMoney20_6 = (
  raw: string,
): bigint | null => {
  const clean = raw.trim();
  if (
    !clean ||
    !MONEY_INPUT.test(clean)
  ) {
    return null;
  }

  const unsigned = clean.startsWith("+")
    ? clean.slice(1)
    : clean;
  const [wholeRaw, fractionRaw = ""] =
    unsigned.split(".");
  const wholeDigits =
    wholeRaw || "0";

  let scaled =
    BigInt(wholeDigits) *
    MONEY_SCALE_FACTOR;

  const keptFraction =
    fractionRaw
      .slice(0, 6)
      .padEnd(6, "0");
  scaled += BigInt(
    keptFraction || "0",
  );

  const roundingDigit =
    fractionRaw.length > 6
      ? fractionRaw.charCodeAt(6) -
        48
      : 0;
  if (roundingDigit >= 5) {
    scaled += 1n;
  }

  if (
    scaled <= 0n ||
    scaled > MONEY_MAX_SCALED
  ) {
    return null;
  }
  return scaled;
};

const multiplyMoney = (
  scaled: bigint,
  multiplier: number,
): bigint | null => {
  const result =
    scaled * BigInt(multiplier);
  return result <= MONEY_MAX_SCALED
    ? result
    : null;
};

const divideMoneyHalfUp = (
  scaled: bigint,
  divisor: number,
): bigint => {
  const divisorBigInt =
    BigInt(divisor);
  let quotient =
    scaled / divisorBigInt;
  const remainder =
    scaled % divisorBigInt;
  if (
    remainder * 2n >=
    divisorBigInt
  ) {
    quotient += 1n;
  }
  return quotient;
};

export type ExactMoneyPair = {
  packagePrice: string | null;
  unitPrice: string;
  independent: boolean;
};

export const deriveExactMoneyPair = (
  hasPackage: boolean,
  unitsRaw: string,
  packageRaw: string,
  unitRaw: string,
): ExactMoneyPair | null => {
  const unitText = unitRaw.trim();
  const unit = unitText
    ? parsePositiveMoney20_6(
        unitText,
      )
    : null;
  if (unitText && unit === null) {
    return null;
  }

  if (!hasPackage) {
    return unit === null
      ? null
      : {
          packagePrice: null,
          unitPrice:
            formatScaledMoney(unit),
          independent: false,
        };
  }

  const units = Number(unitsRaw);
  if (
    !Number.isInteger(units) ||
    units < 2 ||
    units > 1_000_000
  ) {
    return null;
  }

  const packageText =
    packageRaw.trim();
  const packagePrice =
    packageText
      ? parsePositiveMoney20_6(
          packageText,
        )
      : null;
  if (
    packageText &&
    packagePrice === null
  ) {
    return null;
  }

  if (
    packagePrice === null &&
    unit === null
  ) {
    return null;
  }

  let resolvedPackage =
    packagePrice;
  let resolvedUnit = unit;

  if (resolvedPackage === null) {
    if (resolvedUnit === null) {
      return null;
    }
    resolvedPackage =
      multiplyMoney(
        resolvedUnit,
        units,
      );
    if (resolvedPackage === null) {
      return null;
    }
  }

  if (resolvedUnit === null) {
    resolvedUnit =
      divideMoneyHalfUp(
        resolvedPackage,
        units,
      );
    if (resolvedUnit <= 0n) {
      return null;
    }
  }

  return {
    packagePrice:
      formatScaledMoney(
        resolvedPackage,
      ),
    unitPrice:
      formatScaledMoney(
        resolvedUnit,
      ),
    independent:
      packagePrice !== null &&
      unit !== null,
  };
};

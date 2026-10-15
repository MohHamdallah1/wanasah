export const REPRESENTATIVE_PASSWORD_MIN_LENGTH = 8;
export const REPRESENTATIVE_PASSWORD_MAX_UTF8_BYTES = 72;

export type RepresentativePasswordValidation = "tooShort" | "tooLong" | null;

const utf8Encoder = new TextEncoder();

export function representativePasswordUtf8Bytes(value: string): number {
  return utf8Encoder.encode(value).byteLength;
}

export function representativePasswordValidation(value: string): RepresentativePasswordValidation {
  if ([...value].length < REPRESENTATIVE_PASSWORD_MIN_LENGTH) return "tooShort";
  if (representativePasswordUtf8Bytes(value) > REPRESENTATIVE_PASSWORD_MAX_UTF8_BYTES) return "tooLong";
  return null;
}

export function isRepresentativePasswordValid(value: string): boolean {
  return representativePasswordValidation(value) === null;
}

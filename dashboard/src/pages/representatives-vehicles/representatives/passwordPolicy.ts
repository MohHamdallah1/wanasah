export const REPRESENTATIVE_PASSWORD_MIN_LENGTH = 8;
export const REPRESENTATIVE_PASSWORD_MAX_UTF8_BYTES = 72;

const utf8Encoder = new TextEncoder();

export function representativePasswordUtf8Bytes(value: string): number {
  return utf8Encoder.encode(value).byteLength;
}

export function isRepresentativePasswordValid(value: string): boolean {
  return (
    [...value].length >= REPRESENTATIVE_PASSWORD_MIN_LENGTH &&
    representativePasswordUtf8Bytes(value) <= REPRESENTATIVE_PASSWORD_MAX_UTF8_BYTES
  );
}

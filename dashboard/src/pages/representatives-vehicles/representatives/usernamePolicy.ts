const ARABIC_SCRIPT = /\p{Script=Arabic}/u;
const LETTER = /\p{L}/u;
const LATIN = /^[A-Za-z]$/;
const DIGIT = /^[0-9]$/;
const SEPARATORS = new Set([".", "_", "-"]);

export function isRepresentativeUsernameValid(value: string): boolean {
  const username = value.trim();
  if (!username || username.length > 80) return false;

  let hasArabic = false;
  let hasLatin = false;
  let hasLetter = false;

  for (const char of username) {
    const arabicLetter = LETTER.test(char) && ARABIC_SCRIPT.test(char);
    if (arabicLetter) {
      hasArabic = true;
      hasLetter = true;
      continue;
    }
    if (LATIN.test(char)) {
      hasLatin = true;
      hasLetter = true;
      continue;
    }
    if (DIGIT.test(char) || SEPARATORS.has(char)) continue;
    return false;
  }

  return hasLetter && !(hasArabic && hasLatin);
}

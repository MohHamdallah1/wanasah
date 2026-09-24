import {
  useEffect,
  useState,
} from "react";

export function useMediaQuery(
  query: string,
): boolean {
  const getMatch = () =>
    typeof window !== "undefined" &&
    typeof window.matchMedia ===
      "function"
      ? window.matchMedia(query)
          .matches
      : false;

  const [matches, setMatches] =
    useState(getMatch);

  useEffect(() => {
    if (
      typeof window ===
        "undefined" ||
      typeof window.matchMedia !==
        "function"
    ) {
      return;
    }

    const media =
      window.matchMedia(query);
    const sync = () =>
      setMatches(media.matches);

    sync();
    media.addEventListener(
      "change",
      sync,
    );

    return () =>
      media.removeEventListener(
        "change",
        sync,
      );
  }, [query]);

  return matches;
}

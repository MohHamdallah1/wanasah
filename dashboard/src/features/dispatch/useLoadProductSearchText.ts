import { useState } from "react";

/** A changed load context starts at blank search in the same render. */
export function useLoadProductSearchText(context: string) {
  const [draft, setDraft] = useState({ context, text: "" });
  return [draft.context === context ? draft.text : "", (text: string) => setDraft({ context, text })] as const;
}

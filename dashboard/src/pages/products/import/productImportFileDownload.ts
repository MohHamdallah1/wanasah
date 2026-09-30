/** Decode a server-authoritative download without trusting its filename or shape. */
export function saveImportFileArtifact(
  raw: unknown,
  invalidCode: string,
  requireRowCount = false,
): void {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    throw new Error(invalidCode);
  }
  const record = raw as Record<string, unknown>;
  const fileName = record.file_name;
  const contentType = record.content_type;
  const contentBase64 = record.content_base64;
  if (
    typeof fileName !== "string" ||
    !/^[a-zA-Z0-9._-]+\.(csv|xlsx)$/.test(fileName) ||
    typeof contentType !== "string" ||
    ![
      "text/csv; charset=utf-8",
      "text/csv;charset=utf-8",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ].includes(contentType) ||
    typeof contentBase64 !== "string" ||
    contentBase64.length === 0 ||
    (requireRowCount &&
      (!Number.isInteger(record.row_count) ||
        (record.row_count as number) <= 0))
  ) {
    throw new Error(invalidCode);
  }

  let binary: string;
  try {
    binary = window.atob(contentBase64);
  } catch {
    throw new Error(invalidCode);
  }
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const href = URL.createObjectURL(
    new Blob([bytes], { type: contentType }),
  );
  try {
    const link = document.createElement("a");
    link.href = href;
    link.download = fileName;
    link.click();
  } finally {
    URL.revokeObjectURL(href);
  }
}

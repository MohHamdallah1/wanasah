import Papa from "papaparse";

const hasVisibleCell = (
  row: unknown[],
): boolean =>
  row.some((value) =>
    String(value ?? "").trim()
  );

async function csvHasDataRows(
  file: File,
): Promise<boolean | null> {
  try {
    const text =
      await file.text();
    const parsed =
      Papa.parse<string[]>(
        text,
        {
          skipEmptyLines:
            "greedy",
        }
      );
    const rows =
      parsed.data;
    if (!rows.length) {
      return false;
    }
    return rows
      .slice(1)
      .some((row) =>
        hasVisibleCell(row)
      );
  } catch {
    return null;
  }
}

async function xlsxHasDataRows(
  file: File,
): Promise<boolean | null> {
  try {
    const XLSX =
      await import("xlsx");
    const workbook =
      XLSX.read(
        await file.arrayBuffer(),
        {
          type: "array",
        }
      );
    const sheetName =
      workbook.SheetNames[0];
    if (!sheetName) {
      return false;
    }
    const sheet =
      workbook.Sheets[
        sheetName
      ];
    if (!sheet?.["!ref"]) {
      return false;
    }

    const range =
      XLSX.utils.decode_range(
        sheet["!ref"]
      );
    if (
      range.e.r <=
      range.s.r
    ) {
      return false;
    }

    for (
      let rowIndex =
        range.s.r + 1;
      rowIndex <= range.e.r;
      rowIndex += 1
    ) {
      for (
        let columnIndex =
          range.s.c;
        columnIndex <=
        range.e.c;
        columnIndex += 1
      ) {
        const cell =
          sheet[
            XLSX.utils.encode_cell(
              {
                r: rowIndex,
                c: columnIndex,
              }
            )
          ];
        if (
          cell &&
          String(
            cell.v ?? ""
          ).trim()
        ) {
          return true;
        }
      }
    }

    return false;
  } catch {
    // Backend parsing remains authoritative for invalid/corrupted files.
    return null;
  }
}

export async function productImportFileHasDataRows(
  file: File,
): Promise<boolean | null> {
  const lower =
    file.name.toLowerCase();

  if (
    lower.endsWith(".csv")
  ) {
    return csvHasDataRows(
      file
    );
  }
  if (
    lower.endsWith(".xlsx")
  ) {
    return xlsxHasDataRows(
      file
    );
  }
  return null;
}

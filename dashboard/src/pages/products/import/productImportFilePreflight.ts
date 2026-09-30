import Papa from "papaparse";

const readFileAsText = (
  file: File,
): Promise<string> => {
  if (
    typeof file.text ===
    "function"
  ) {
    return file.text();
  }
  return new Promise(
    (resolve, reject) => {
      const reader =
        new FileReader();
      reader.onload = () =>
        resolve(
          String(
            reader.result ?? ""
          )
        );
      reader.onerror = () =>
        reject(
          reader.error ??
            new Error(
              "FILE_READ_FAILED"
            )
        );
      reader.readAsText(file);
    }
  );
};

const readFileAsArrayBuffer = (
  file: File,
): Promise<ArrayBuffer> => {
  if (
    typeof file.arrayBuffer ===
    "function"
  ) {
    return file.arrayBuffer();
  }
  return new Promise(
    (resolve, reject) => {
      const reader =
        new FileReader();
      reader.onload = () => {
        if (
          reader.result instanceof
          ArrayBuffer
        ) {
          resolve(
            reader.result
          );
          return;
        }
        reject(
          new Error(
            "FILE_READ_FAILED"
          )
        );
      };
      reader.onerror = () =>
        reject(
          reader.error ??
            new Error(
              "FILE_READ_FAILED"
            )
        );
      reader.readAsArrayBuffer(
        file
      );
    }
  );
};

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
      await readFileAsText(
        file
      );
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
        await readFileAsArrayBuffer(
          file
        ),
        {
          type: "array",
        }
      );
    // Mirror backend worksheet authority: official templates identify their
    // product sheet through _wanasah_meta!A2; external workbooks need exactly
    // one visible sheet. Ambiguity belongs to backend validation, not a
    // false browser-side `no data rows` rejection of the first sheet.
    const meta = workbook.Sheets["_wanasah_meta"];
    let sheetName: string;
    if (meta) {
      const marker = String(meta.A1?.v ?? "").trim();
      const declared = String(meta.A2?.v ?? "").trim();
      const index = workbook.SheetNames.indexOf(declared);
      if (
        marker !== "WANASAH_PRODUCT_IMPORT_V1" ||
        index < 0 ||
        workbook.Workbook?.Sheets?.[index]?.Hidden
      ) {
        return null;
      }
      sheetName = declared;
    } else {
      const visibleNames = workbook.SheetNames.filter(
        (_name, index) => !workbook.Workbook?.Sheets?.[index]?.Hidden,
      );
      if (visibleNames.length !== 1) {
        return null;
      }
      sheetName = visibleNames[0];
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

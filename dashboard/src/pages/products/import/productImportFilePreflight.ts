import Papa from "papaparse";

export type ProductImportTrackingFallbackStatus =
  | "NOT_NEEDED"
  | "NEEDED"
  | "UNKNOWN";

export type ProductImportTrackingFallbackAnalysis = {
  status: ProductImportTrackingFallbackStatus;
  dataRows: number | null;
  lotFallbackRows: number | null;
  expiryFallbackRows: number | null;
};

export type ProductImportFilePreflightResult = {
  hasDataRows: boolean | null;
  tracking: ProductImportTrackingFallbackAnalysis;
};

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

const normalizeToken = (
  value: unknown,
): string =>
  String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ");

const LOT_HEADERS = new Set(
  [
    "lot_control_mode",
    "lot control",
    "lot tracking",
    "batch tracking",
    "lot control mode",
    "batch control mode",
    "تتبع الدفعة",
    "تتبع الدفعات",
    "تتبع التشغيلة",
    "نمط تتبع الدفعة",
  ].map(normalizeToken),
);

const EXPIRY_HEADERS = new Set(
  [
    "expiry_control_mode",
    "expiry control",
    "expiry tracking",
    "expiration tracking",
    "expiry control mode",
    "expiration control mode",
    "تتبع الصلاحية",
    "تتبع تاريخ الصلاحية",
    "نمط تتبع الصلاحية",
  ].map(normalizeToken),
);

const DEFAULT_VALUES = new Set(
  [
    "",
    "__DEFAULT__",
    "use default",
    "default",
    "استخدام الافتراضي",
    "افتراضي",
  ].map(normalizeToken),
);

const usesFallback = (
  value: unknown,
): boolean =>
  DEFAULT_VALUES.has(
    normalizeToken(value),
  );

const unknownTracking = (
  dataRows: number | null,
): ProductImportTrackingFallbackAnalysis => ({
  status: "UNKNOWN",
  dataRows,
  lotFallbackRows: null,
  expiryFallbackRows: null,
});

const analyzeRows = (
  headers: unknown[],
  dataRows: unknown[][],
): ProductImportTrackingFallbackAnalysis => {
  const normalizedHeaders =
    headers.map(normalizeToken);
  const lotIndex =
    normalizedHeaders.findIndex(
      (header) =>
        LOT_HEADERS.has(header),
    );
  const expiryIndex =
    normalizedHeaders.findIndex(
      (header) =>
        EXPIRY_HEADERS.has(
          header,
        ),
    );

  if (
    lotIndex < 0 ||
    expiryIndex < 0
  ) {
    return unknownTracking(
      dataRows.length,
    );
  }

  let lotFallbackRows = 0;
  let expiryFallbackRows = 0;
  for (const row of dataRows) {
    if (
      usesFallback(
        row[lotIndex],
      )
    ) {
      lotFallbackRows += 1;
    }
    if (
      usesFallback(
        row[expiryIndex],
      )
    ) {
      expiryFallbackRows += 1;
    }
  }

  return {
    status:
      lotFallbackRows > 0 ||
      expiryFallbackRows > 0
        ? "NEEDED"
        : "NOT_NEEDED",
    dataRows:
      dataRows.length,
    lotFallbackRows,
    expiryFallbackRows,
  };
};

async function inspectCsv(
  file: File,
): Promise<ProductImportFilePreflightResult> {
  try {
    const text =
      await readFileAsText(
        file,
      );
    const parsed =
      Papa.parse<unknown[]>(
        text,
        {
          skipEmptyLines:
            "greedy",
        },
      );
    const rows = parsed.data;
    if (!rows.length) {
      return {
        hasDataRows: false,
        tracking: {
          status: "NOT_NEEDED",
          dataRows: 0,
          lotFallbackRows: 0,
          expiryFallbackRows: 0,
        },
      };
    }

    const dataRows =
      rows
        .slice(1)
        .filter(
          hasVisibleCell,
        );
    return {
      hasDataRows:
        dataRows.length > 0,
      tracking:
        analyzeRows(
          rows[0],
          dataRows,
        ),
    };
  } catch {
    return {
      hasDataRows: null,
      tracking:
        unknownTracking(null),
    };
  }
}

async function inspectXlsx(
  file: File,
): Promise<ProductImportFilePreflightResult> {
  try {
    const XLSX =
      await import("xlsx");
    const workbook =
      XLSX.read(
        await readFileAsArrayBuffer(
          file,
        ),
        {
          type: "array",
        },
      );

    const meta =
      workbook.Sheets[
        "_wanasah_meta"
      ];
    let sheetName: string;
    if (meta) {
      const marker =
        String(
          meta.A1?.v ?? "",
        ).trim();
      const declared =
        String(
          meta.A2?.v ?? "",
        ).trim();
      const index =
        workbook.SheetNames.indexOf(
          declared,
        );
      if (
        marker !==
          "WANASAH_PRODUCT_IMPORT_V1" ||
        index < 0 ||
        workbook.Workbook
          ?.Sheets?.[index]
          ?.Hidden
      ) {
        return {
          hasDataRows: null,
          tracking:
            unknownTracking(
              null,
            ),
        };
      }
      sheetName = declared;
    } else {
      const visibleNames =
        workbook.SheetNames.filter(
          (_name, index) =>
            !workbook.Workbook
              ?.Sheets?.[index]
              ?.Hidden,
        );
      if (
        visibleNames.length !==
        1
      ) {
        return {
          hasDataRows: null,
          tracking:
            unknownTracking(
              null,
            ),
        };
      }
      sheetName =
        visibleNames[0];
    }

    const sheet =
      workbook.Sheets[
        sheetName
      ];
    if (!sheet?.["!ref"]) {
      return {
        hasDataRows: false,
        tracking: {
          status: "NOT_NEEDED",
          dataRows: 0,
          lotFallbackRows: 0,
          expiryFallbackRows: 0,
        },
      };
    }

    const range =
      XLSX.utils.decode_range(
        sheet["!ref"],
      );
    if (
      range.e.r <=
      range.s.r
    ) {
      return {
        hasDataRows: false,
        tracking: {
          status: "NOT_NEEDED",
          dataRows: 0,
          lotFallbackRows: 0,
          expiryFallbackRows: 0,
        },
      };
    }

    const headers: unknown[] =
      [];
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
              r: range.s.r,
              c: columnIndex,
            },
          )
        ];
      headers.push(
        cell?.v ?? "",
      );
    }

    const normalizedHeaders =
      headers.map(
        normalizeToken,
      );
    const lotRelativeIndex =
      normalizedHeaders.findIndex(
        (header) =>
          LOT_HEADERS.has(
            header,
          ),
      );
    const expiryRelativeIndex =
      normalizedHeaders.findIndex(
        (header) =>
          EXPIRY_HEADERS.has(
            header,
          ),
      );

    let dataRows = 0;
    let lotFallbackRows = 0;
    let expiryFallbackRows = 0;

    for (
      let rowIndex =
        range.s.r + 1;
      rowIndex <= range.e.r;
      rowIndex += 1
    ) {
      let visible = false;
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
              },
            )
          ];
        if (
          String(
            cell?.v ?? "",
          ).trim()
        ) {
          visible = true;
          break;
        }
      }
      if (!visible) {
        continue;
      }

      dataRows += 1;
      if (
        lotRelativeIndex >= 0
      ) {
        const cell =
          sheet[
            XLSX.utils.encode_cell(
              {
                r: rowIndex,
                c:
                  range.s.c +
                  lotRelativeIndex,
              },
            )
          ];
        if (
          usesFallback(
            cell?.v,
          )
        ) {
          lotFallbackRows += 1;
        }
      }
      if (
        expiryRelativeIndex >=
        0
      ) {
        const cell =
          sheet[
            XLSX.utils.encode_cell(
              {
                r: rowIndex,
                c:
                  range.s.c +
                  expiryRelativeIndex,
              },
            )
          ];
        if (
          usesFallback(
            cell?.v,
          )
        ) {
          expiryFallbackRows += 1;
        }
      }
    }

    if (
      lotRelativeIndex < 0 ||
      expiryRelativeIndex < 0
    ) {
      return {
        hasDataRows:
          dataRows > 0,
        tracking:
          unknownTracking(
            dataRows,
          ),
      };
    }

    return {
      hasDataRows:
        dataRows > 0,
      tracking: {
        status:
          lotFallbackRows > 0 ||
          expiryFallbackRows >
            0
            ? "NEEDED"
            : "NOT_NEEDED",
        dataRows,
        lotFallbackRows,
        expiryFallbackRows,
      },
    };
  } catch {
    return {
      hasDataRows: null,
      tracking:
        unknownTracking(null),
    };
  }
}

export async function inspectProductImportFile(
  file: File,
): Promise<ProductImportFilePreflightResult> {
  const lower =
    file.name.toLowerCase();

  if (
    lower.endsWith(
      ".csv",
    )
  ) {
    return inspectCsv(file);
  }
  if (
    lower.endsWith(
      ".xlsx",
    )
  ) {
    return inspectXlsx(file);
  }
  return {
    hasDataRows: null,
    tracking:
      unknownTracking(null),
  };
}

export async function productImportFileHasDataRows(
  file: File,
): Promise<boolean | null> {
  return (
    await inspectProductImportFile(
      file,
    )
  ).hasDataRows;
}

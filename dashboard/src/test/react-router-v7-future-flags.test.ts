import {
  readFileSync,
} from "node:fs";
import {
  describe,
  expect,
  it,
} from "vitest";

const source = (
  relativePath: string,
): string =>
  readFileSync(
    new URL(
      relativePath,
      import.meta.url,
    ),
    "utf8",
  ).replace(/\s+/g, " ");

describe(
  "React Router v7 future compatibility",
  () => {
    it("enables the v7 future flags in the production BrowserRouter", () => {
      const app = source(
        "../App.tsx",
      );

      expect(app).toContain(
        "v7_startTransition: true",
      );
      expect(app).toContain(
        "v7_relativeSplatPath: true",
      );
    });

    it("runs MemoryRouter tests with the same future behavior", () => {
      const runtimeTest = source(
        "./advanced-uom-p5.test.tsx",
      );

      expect(runtimeTest).toContain(
        "v7_startTransition: true",
      );
      expect(runtimeTest).toContain(
        "v7_relativeSplatPath: true",
      );
    });

    it("keeps the catch-all route free of relative router navigation assumptions", () => {
      const notFound = source(
        "../pages/NotFound.tsx",
      );

      expect(notFound).not.toContain(
        "useNavigate(",
      );
      expect(notFound).not.toContain(
        "<Link",
      );
      expect(notFound).not.toContain(
        "<NavLink",
      );
      expect(notFound).toContain(
        'href="/"',
      );
    });
  },
);

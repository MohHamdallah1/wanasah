import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const mocks = vi.hoisted(() => ({
  authFetch: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock(
  "@/hooks/useAuthFetch",
  () => ({
    useAuthFetch: () =>
      mocks.authFetch,
  }),
);

vi.mock(
  "@/hooks/useNetworkStatus",
  () => ({
    useNetworkStatus: () => true,
  }),
);

vi.mock(
  "sonner",
  () => ({
    toast: {
      error: mocks.toastError,
      success: mocks.toastSuccess,
    },
  }),
);

vi.mock(
  "react-i18next",
  () => ({
    useTranslation: () => ({
      t: (key: string) => key,
      i18n: {
        language: "en",
        resolvedLanguage: "en",
        dir: () => "ltr",
      },
    }),
  }),
);

vi.mock(
  "@/components/ui/modal",
  () => ({
    Modal: ({
      isOpen,
      children,
    }: {
      isOpen: boolean;
      children: React.ReactNode;
    }) =>
      isOpen ? (
        <div>{children}</div>
      ) : null,
  }),
);

import { ProductFamiliesManager } from "../pages/products/ProductFamiliesManager";

const family = (
  id: number,
  name: string,
) => ({
  id,
  name,
  version: 1,
  variant_count: 0,
});

describe(
  "ProductFamiliesManager P4 runtime",
  () => {
    let queryClient: QueryClient;

    beforeEach(() => {
      mocks.authFetch.mockReset();
      mocks.toastError.mockReset();
      mocks.toastSuccess.mockReset();
      localStorage.clear();
      queryClient =
        new QueryClient({
          defaultOptions: {
            queries: {
              retry: false,
            },
            mutations: {
              retry: false,
            },
          },
        });
    });

    afterEach(() => {
      queryClient.clear();
      vi.restoreAllMocks();
    });

    it("paginates with the server cursor and resets continuation when search changes", async () => {
      mocks.authFetch.mockImplementation(
        async (url: string) => {
          const parsed =
            new URL(
              url,
              "https://test.local",
            );
          const search =
            parsed.searchParams.get(
              "search",
            );
          const cursor =
            parsed.searchParams.get(
              "cursor",
            );

          if (search === "Gamma") {
            expect(cursor).toBeNull();
            return {
              items: [
                family(
                  3,
                  "Gamma Family",
                ),
              ],
              next_cursor: null,
              has_more: false,
            };
          }

          if (
            cursor ===
            "next.family.cursor"
          ) {
            return {
              items: [
                family(
                  2,
                  "Beta Family",
                ),
              ],
              next_cursor: null,
              has_more: false,
            };
          }

          return {
            items: [
              family(
                1,
                "Alpha Family",
              ),
            ],
            next_cursor:
              "next.family.cursor",
            has_more: true,
          };
        },
      );

      const view = render(
        <QueryClientProvider
          client={queryClient}
        >
          <ProductFamiliesManager
            isOpen
            companyId={1}
            driverId={2}
            onClose={vi.fn()}
          />
        </QueryClientProvider>,
      );

      expect(
        await screen.findByText(
          "Alpha Family",
        ),
      ).toBeInTheDocument();

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name: "products.familyNext",
          },
        ),
      );

      expect(
        await screen.findByText(
          "Beta Family",
        ),
      ).toBeInTheDocument();

      expect(
        mocks.authFetch.mock.calls.some(
          ([url]) =>
            String(url).includes(
              "cursor=next.family.cursor",
            ),
        ),
      ).toBe(true);

      fireEvent.change(
        screen.getByPlaceholderText(
          "products.familySearchPlaceholder",
        ),
        {
          target: {
            value: "Gamma",
          },
        },
      );

      expect(
        await screen.findByText(
          "Gamma Family",
          {},
          {
            timeout: 1500,
          },
        ),
      ).toBeInTheDocument();

      const gammaCall =
        mocks.authFetch.mock.calls.find(
          ([url]) =>
            String(url).includes(
              "search=Gamma",
            ),
        );
      expect(gammaCall).toBeDefined();
      expect(
        String(
          gammaCall?.[0],
        ),
      ).not.toContain(
        "cursor=",
      );

      view.unmount();
    });

    it("keeps a request failure distinct from an empty family result", async () => {
      mocks.authFetch.mockRejectedValueOnce(
        new Error("network"),
      );

      render(
        <QueryClientProvider
          client={queryClient}
        >
          <ProductFamiliesManager
            isOpen
            companyId={1}
            driverId={2}
            onClose={vi.fn()}
          />
        </QueryClientProvider>,
      );

      expect(
        await screen.findByText(
          "products.errors.familiesLoad",
        ),
      ).toBeInTheDocument();

      expect(
        screen.queryByText(
          "products.noFamilies",
        ),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole(
          "button",
          {
            name: "common.retry",
          },
        ),
      ).toBeInTheDocument();
    });
  },
);

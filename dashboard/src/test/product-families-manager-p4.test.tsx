import {
  cleanup,
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

import {
  durableScope,
  getOrCreateDurableCommand,
} from "../lib/durableOperations";
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
      cleanup();
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

    it("restores an ambiguous family create after remount and retries the exact same request id", async () => {
      const postBodies: Array<{
        request_id: string;
        name: string;
      }> = [];
      let postAttempt = 0;

      mocks.authFetch.mockImplementation(
        async (
          _url: string,
          options?: RequestInit,
        ) => {
          if (
            options?.method ===
            "POST"
          ) {
            postAttempt += 1;
            postBodies.push(
              JSON.parse(
                String(
                  options.body,
                ),
              ),
            );
            if (
              postAttempt === 1
            ) {
              throw Object.assign(
                new Error("network"),
                {
                  code:
                    "NETWORK_UNAVAILABLE",
                  status: 0,
                },
              );
            }
            return {
              id: 90,
              name:
                "Alpha Family",
              version: 1,
              variant_count: 0,
            };
          }

          return {
            items: [],
            next_cursor: null,
            has_more: false,
          };
        },
      );

      const firstView = render(
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

      await screen.findByText(
        "products.noFamilies",
      );

      const firstInput =
        screen.getByPlaceholderText(
          "products.newFamilyPlaceholder",
        );
      const firstAdd =
        screen.getByRole(
          "button",
          {
            name:
              "products.addFamily",
          },
        );

      fireEvent.change(
        firstInput,
        {
          target: {
            value:
              "Alpha Family",
          },
        },
      );
      fireEvent.click(firstAdd);

      await waitFor(() => {
        expect(
          mocks.toastError,
        ).toHaveBeenCalled();
      });
      await waitFor(() => {
        expect(
          firstInput,
        ).toBeDisabled();
      });

      firstView.unmount();

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

      const restoredInput =
        await screen.findByDisplayValue(
          "Alpha Family",
        );
      expect(
        restoredInput,
      ).toBeDisabled();
      expect(
        screen.getByText(
          "products.familyPendingRetry",
        ),
      ).toBeInTheDocument();

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name:
              "products.addFamily",
          },
        ),
      );

      await waitFor(() => {
        expect(
          mocks.toastSuccess,
        ).toHaveBeenCalledWith(
          "products.familyCreated",
        );
      });

      expect(
        postBodies,
      ).toHaveLength(2);
      expect(
        postBodies[1]
          .request_id,
      ).toBe(
        postBodies[0]
          .request_id,
      );
      expect(
        postBodies[1].name,
      ).toBe(
        "Alpha Family",
      );
    });

    it("locks the exact family create payload after an ambiguous outcome", async () => {
      const postBodies: Array<{
        request_id: string;
        name: string;
      }> = [];

      mocks.authFetch.mockImplementation(
        async (
          _url: string,
          options?: RequestInit,
        ) => {
          if (
            options?.method ===
            "POST"
          ) {
            postBodies.push(
              JSON.parse(
                String(
                  options.body,
                ),
              ),
            );
            throw Object.assign(
              new Error("network"),
              {
                code:
                  "NETWORK_UNAVAILABLE",
                status: 0,
              },
            );
          }

          return {
            items: [],
            next_cursor: null,
            has_more: false,
          };
        },
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

      await screen.findByText(
        "products.noFamilies",
      );

      const nameInput =
        screen.getByPlaceholderText(
          "products.newFamilyPlaceholder",
        );
      const addButton =
        screen.getByRole(
          "button",
          {
            name:
              "products.addFamily",
          },
        );

      fireEvent.change(
        nameInput,
        {
          target: {
            value:
              "Alpha Family",
          },
        },
      );
      fireEvent.click(addButton);

      await waitFor(() => {
        expect(
          postBodies,
        ).toHaveLength(1);
      });
      await waitFor(() => {
        expect(
          nameInput,
        ).toBeDisabled();
      });

      expect(
        nameInput,
      ).toHaveValue(
        "Alpha Family",
      );
      expect(
        postBodies[0].name,
      ).toBe(
        "Alpha Family",
      );
    });

    it("keeps a malformed successful family response pending and locks the original payload", async () => {
      const postBodies: Array<{
        request_id: string;
        name: string;
      }> = [];

      mocks.authFetch.mockImplementation(
        async (
          _url: string,
          options?: RequestInit,
        ) => {
          if (
            options?.method ===
            "POST"
          ) {
            postBodies.push(
              JSON.parse(
                String(
                  options.body,
                ),
              ),
            );
            return {};
          }

          return {
            items: [],
            next_cursor: null,
            has_more: false,
          };
        },
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

      await screen.findByText(
        "products.noFamilies",
      );

      const nameInput =
        screen.getByPlaceholderText(
          "products.newFamilyPlaceholder",
        );
      const addButton =
        screen.getByRole(
          "button",
          {
            name:
              "products.addFamily",
          },
        );

      fireEvent.change(
        nameInput,
        {
          target: {
            value:
              "Alpha Family",
          },
        },
      );
      fireEvent.click(addButton);

      await waitFor(() => {
        expect(
          mocks.toastError,
        ).toHaveBeenCalled();
      });
      await waitFor(() => {
        expect(
          nameInput,
        ).toBeDisabled();
      });

      expect(
        screen.getByText(
          "products.familyPendingRetry",
        ),
      ).toBeInTheDocument();
      expect(
        postBodies,
      ).toHaveLength(1);
      expect(
        postBodies[0].name,
      ).toBe(
        "Alpha Family",
      );
    });

    it("fails closed when a persisted family create command is corrupted", async () => {
      const scope = durableScope(
        1,
        2,
        "family-create",
      );
      await getOrCreateDurableCommand(
        scope,
        {
          name: "Alpha Family",
        },
      );

      const raw =
        localStorage.getItem(scope);
      expect(raw).not.toBeNull();
      const stored = JSON.parse(
        String(raw),
      ) as {
        payload: {
          name: string;
        };
      };
      stored.payload.name =
        "Tampered Family";
      localStorage.setItem(
        scope,
        JSON.stringify(stored),
      );

      mocks.authFetch.mockResolvedValue({
        items: [],
        next_cursor: null,
        has_more: false,
      });

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
          "products.familyPendingBlocked",
        ),
      ).toBeInTheDocument();

      expect(
        screen.getByPlaceholderText(
          "products.newFamilyPlaceholder",
        ),
      ).toBeDisabled();
      expect(
        screen.getByRole(
          "button",
          {
            name:
              "products.addFamily",
          },
        ),
      ).toBeDisabled();

      expect(
        mocks.authFetch.mock.calls.filter(
          ([, options]) =>
            options?.method ===
            "POST",
        ),
      ).toHaveLength(0);
      expect(
        localStorage.getItem(scope),
      ).not.toBeNull();
    });

    it("restores a pending family rename with its original expected version", async () => {
      const scope = durableScope(
        1,
        2,
        "family-rename",
        7,
      );
      const command =
        await getOrCreateDurableCommand(
          scope,
          {
            expected_version: 1,
            name: "Renamed Family",
          },
        );

      const patchBodies: Array<{
        request_id: string;
        expected_version: number;
        name: string;
      }> = [];

      mocks.authFetch.mockImplementation(
        async (
          _url: string,
          options?: RequestInit,
        ) => {
          if (
            options?.method ===
            "PATCH"
          ) {
            patchBodies.push(
              JSON.parse(
                String(
                  options.body,
                ),
              ),
            );
            return {
              id: 7,
              name:
                "Renamed Family",
              version: 2,
            };
          }

          return {
            items: [
              family(
                7,
                "Original Family",
              ),
            ],
            next_cursor: null,
            has_more: false,
          };
        },
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
          "Original Family",
        ),
      ).toBeInTheDocument();

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name: "common.edit",
          },
        ),
      );

      const renameInput =
        await screen.findByDisplayValue(
          "Renamed Family",
        );
      expect(
        renameInput,
      ).toBeDisabled();

      fireEvent.click(
        screen.getByRole(
          "button",
          {
            name: "common.save",
          },
        ),
      );

      await waitFor(() => {
        expect(
          mocks.toastSuccess,
        ).toHaveBeenCalledWith(
          "products.familyUpdated",
        );
      });

      expect(
        patchBodies,
      ).toHaveLength(1);
      expect(
        patchBodies[0],
      ).toEqual({
        request_id:
          command.requestId,
        expected_version: 1,
        name: "Renamed Family",
      });
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

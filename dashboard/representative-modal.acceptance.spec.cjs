const { test, expect } = require("@playwright/test");

const base = "http://127.0.0.1:4182/representative-modal-acceptance.html";
const widths = [320, 375, 768, 1024, 1440];
const kinds = ["create", "edit", "lifecycle", "credentials"];

async function assertLayer(page, width) {
  const layer = page.locator(".app-modal");
  const backdrop = page.locator(".app-modal-backdrop");
  const panel = page.locator(".app-modal-panel");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.waitForTimeout(400);
  expect(await layer.evaluate((el) => el.parentElement === document.body)).toBe(true);
  expect(await layer.evaluate((el) => getComputedStyle(el).position)).toBe("fixed");
  const overlayBox = await backdrop.boundingBox();
  expect(overlayBox).not.toBeNull();
  expect(Math.round(overlayBox.x)).toBe(0);
  expect(Math.round(overlayBox.y)).toBe(0);
  expect(Math.round(overlayBox.width)).toBe(width);
  expect(Math.round(overlayBox.height)).toBe(800);
  const topElementIsBackdrop = await page.evaluate(() => {
    const el = document.elementFromPoint(4, 4);
    return Boolean(el && el.classList.contains("app-modal-backdrop"));
  });
  expect(topElementIsBackdrop).toBe(true);
  const panelBox = await panel.boundingBox();
  expect(panelBox).not.toBeNull();
  expect(panelBox.y).toBeGreaterThanOrEqual(0);
  expect(panelBox.y + panelBox.height).toBeLessThanOrEqual(800.5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
}

for (const width of widths) {
  for (const kind of kinds) {
    test(`Arabic ${kind} modal covers app chrome at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto(`${base}?lang=ar`);
      await page.getByTestId(`open-${kind}`).click();
      await assertLayer(page, width);
      await expect(page.getByTestId("app-header")).toBeVisible();
      if (width >= 1024) {
        expect(await page.getByTestId("app-header").evaluate((el) => getComputedStyle(el.closest(".workspace-top-bar-frame")).zIndex)).toBe("40");
        expect(await page.locator(".app-modal").evaluate((el) => getComputedStyle(el).zIndex)).toBe("50");
      }
      const body = page.locator(".app-modal-body");
      await body.evaluate((el) => { el.scrollTop = el.scrollHeight; });
      await expect(page.locator(".app-modal-header")).toBeVisible();
    });
  }
}

test("Arabic create uses compact copy and preserves the debt label without visible debt paragraph", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto(`${base}?lang=ar`);
  await page.getByTestId("open-create").click();
  await expect(page.getByText("استخدم العربية أو الإنجليزية دون خلط، ويمكن إضافة الأرقام و . _ -")).toBeVisible();
  await expect(page.getByText("استخدم أحرفًا عربية أو إنجليزية، ويمكن إضافة الأرقام و . _ - دون خلط العربية والإنجليزية في الاسم نفسه.")).toHaveCount(0);
  await expect(page.getByText("هذا الحد هو أقصى مبلغ ذمم جديد في عملية بيع واحدة. ليس حدًا يوميًا ولا يتجدد تلقائيًا، ويظل سقف ذمة المحل مطبقًا بشكل مستقل.")).toHaveCount(0);
  await page.getByLabel("السماح بالبيع بالذمم").check();
  await expect(page.getByLabel("حد الذمم لكل عملية بيع")).toBeVisible();
  await expect(page.locator("#representative-debt-hint")).toHaveClass(/sr-only/);
  await expect(page.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("English LTR uses the compact username helper and concise debt label", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 });
  await page.goto(`${base}?lang=en`);
  await page.getByTestId("open-create").click();
  expect(await page.locator("html").getAttribute("dir")).toBe("ltr");
  await expect(page.getByText("Use Arabic or Latin letters without mixing them; numbers and . _ - are allowed.")).toBeVisible();
  await page.getByLabel("Allow credit sales").check();
  await expect(page.getByLabel("Debt limit per sale")).toBeVisible();
  await expect(page.getByText("This is the maximum new credit for a single sale. It is not a daily limit and does not reset automatically. The shop’s total credit limit still applies independently.")).toHaveCount(0);
});

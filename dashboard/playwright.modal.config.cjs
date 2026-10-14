module.exports = {
  testDir: ".",
  testMatch: "representative-modal.acceptance.spec.cjs",
  workers: 1,
  reporter: "line",
  use: { headless: true, channel: "chrome" },
};

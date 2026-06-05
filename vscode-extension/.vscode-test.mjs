import { defineConfig } from "@vscode/test-cli";

// Integration tests run in a downloaded VS Code instance. Requires a display
// (use xvfb-run on headless Linux CI). The compiled test files live in out/.
export default defineConfig({
  files: "out/test/suite/**/*.test.js",
  version: "stable",
  mocha: {
    ui: "bdd",
    timeout: 20000,
  },
});

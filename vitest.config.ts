import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: [".pi/extensions/**/*.test.ts", "bin/**/*.test.mjs"],
  },
});

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Vitest reads its settings here too. A test is src/**/*.test.ts(x); the AI factory ties a test to its
// criterion by the tag in its name — it("shows the total [AC R-001.AC-1]", …) — and runs one with -t.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test-setup.ts"],
  },
});

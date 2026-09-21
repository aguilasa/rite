import assert from "node:assert/strict";
import test from "node:test";

test("the generated entry point loads", async () => {
  const mod = await import("../src/index.mjs");
  assert.equal(typeof mod, "object");
});

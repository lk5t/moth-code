import { expect, it } from "vitest";
import { parseScope } from "@/features/settings/ServersSection";

it("splits a pasted scope list on spaces, commas, semicolons and new lines", () => {
  expect(parseScope("10.0.0.0/24\n*.acme-test.com, 203.0.113.7;  app.example.org")).toEqual(
    ["10.0.0.0/24", "*.acme-test.com", "203.0.113.7", "app.example.org"]);
});

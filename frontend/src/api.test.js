import { describe, expect, it } from "vitest";
import { validatePdf } from "./api.js";

describe("PDF validation", () => {
  it("accepts a non-empty PDF within the upload limit", () => {
    const file = new File(["pdf"], "lecture.pdf", { type: "application/pdf" });
    expect(() => validatePdf(file)).not.toThrow();
  });

  it("rejects a non-PDF and an oversized PDF", () => {
    const text = new File(["notes"], "notes.txt", { type: "text/plain" });
    const oversized = new File(
      [new Uint8Array(10 * 1024 * 1024 + 1)],
      "large.pdf",
      { type: "application/pdf" },
    );
    expect(() => validatePdf(text)).toThrow(/Only PDF/);
    expect(() => validatePdf(oversized)).toThrow(/10 MiB/);
  });
});

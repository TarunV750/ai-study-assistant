import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.jsx";
import * as api from "./api.js";

vi.mock("./api.js", () => ({
  askQuestion: vi.fn(),
  createStudyMaterial: vi.fn(),
  getDocument: vi.fn(),
  listDocuments: vi.fn(),
  uploadPdf: vi.fn(),
}));

const DOCUMENT_ID = "ac778e44-2980-4aa5-a4de-553c59c97d81";

describe("CourseLens workspace", () => {
  beforeEach(() => {
    api.listDocuments.mockResolvedValue({
      documents: [
        {
          documentId: DOCUMENT_ID,
          filename: "lecture04-Git.pdf",
          status: "INDEXED",
        },
      ],
    });
    api.createStudyMaterial.mockResolvedValue({
      title: "Study guide",
      content: "Git workflow [Source 1]",
      sources: [{ sourceNumber: 1 }],
    });
    api.askQuestion.mockResolvedValue({
      answer: "Configure Git locally. [Source 1]",
      sources: [
        {
          sourceNumber: 1,
          chunkId: "chunk-1",
          filename: "lecture04-Git.pdf",
          pageNumber: 2,
        },
      ],
    });
  });

  it("requires a selected ready document before generating study material", async () => {
    render(<App />);
    const document = await screen.findByRole("button", { name: /lecture04-Git.pdf/i });
    const generate = screen.getByRole("button", { name: "Generate" });
    expect(generate).toBeDisabled();

    fireEvent.click(document);
    expect(generate).toBeEnabled();
    fireEvent.click(generate);

    await waitFor(() =>
      expect(api.createStudyMaterial).toHaveBeenCalledWith(
        expect.objectContaining({ documentIds: [DOCUMENT_ID] }),
      ),
    );
    expect(await screen.findByText("Git workflow [Source 1]")).toBeVisible();
  });

  it("submits a question with the selected document and renders its citation", async () => {
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /lecture04-Git.pdf/i }));
    fireEvent.change(screen.getByPlaceholderText(/Ask about a concept/), {
      target: { value: "What is the first workflow step?" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ask →" }));

    await waitFor(() =>
      expect(api.askQuestion).toHaveBeenCalledWith(
        "What is the first workflow step?",
        [DOCUMENT_ID],
      ),
    );
    expect(await screen.findByText(/Configure Git locally/)).toBeVisible();
    expect(screen.getByText(/lecture04-Git.pdf p. 2/)).toBeVisible();
  });
});

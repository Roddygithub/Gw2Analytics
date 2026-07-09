import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

/**
 * Vitest partial mock: keep the real ``ApiError`` + ``formatApiError``
 * surface so the page tests against the actual error class. We only
 * stub ``uploadLog`` + ``fetchUploadStatus`` (the two network
 * surfaces the wizard drives). If the real ``ApiError`` constructor
 * gains fields, the tests still validate against the real class --
 * the mock cannot silently drift.
 */
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    uploadLog: vi.fn(),
    fetchUploadStatus: vi.fn(),
  };
});

import UploadPage from "@/app/upload/page";
import {
  ApiError,
  fetchUploadStatus,
  uploadLog,
} from "@/lib/api";

/**
 * Wizard-flow smoke for the upload page.
 *
 * The wizard replaces the legacy 1-step flow (file input -> POST ->
 * result card) with a 3-step state machine:
 *   pick -> upload -> parse -> done.
 * Each step has its own affordance + data-testid so the e2e suite
 * (Playwright ``tests/e2e/upload.spec.ts``) can probe the same
 * surface. The 5 legacy cases are kept + 2 new cases added to cover
 * the new step transitions.
 */
function makeFile(name = "fight-2026-07-07.zevtc", bytes = 4096): File {
  const blob = new Blob([new Uint8Array(bytes)], {
    type: "application/octet-stream",
  });
  return new File([blob], name, { type: "application/octet-stream" });
}

describe("UploadPage wizard", () => {
  it("renders the heading + step indicator + disabled Next (v0.9.0)", () => {
    render(<UploadPage />);
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /Upload a .zevtc replay/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("step-pick")).toBeInTheDocument();
    expect(screen.getByTestId("step-indicator-pick")).toHaveAttribute(
      "aria-current",
      "step",
    );
    expect(screen.getByTestId("file-chip")).toHaveTextContent(
      "No file selected",
    );
    expect(screen.getByTestId("next")).toBeDisabled();
  });

  it("rejects non-.zevtc files before leaving the pick step (v0.9.0)", () => {
    render(<UploadPage />);
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile("evil.exe")] } });
    expect(screen.getByTestId("next")).toBeDisabled();
    expect(screen.getByTestId("rejected")).toHaveTextContent(
      "Only .zevtc files are accepted.",
    );
    expect(uploadLog).not.toHaveBeenCalled();
  });

  it("uploads a valid .zevtc and transitions to step 3 (parse) (v0.9.0)", async () => {
    vi.mocked(uploadLog).mockResolvedValue({
      id: "11111111-2222-3333-4444-555555555555",
      sha256: "abcdef0123456789".repeat(4),
      status: "pending",
    });
    render(<UploadPage />);
    fireEvent.change(screen.getByTestId("file-input") as HTMLInputElement, {
      target: { files: [makeFile("fight-2026-07-07.zevtc")] },
    });
    fireEvent.click(screen.getByTestId("next"));

    await waitFor(() => expect(uploadLog).toHaveBeenCalledTimes(1));
    const forwarded = vi.mocked(uploadLog).mock.calls[0]?.[0];
    expect(forwarded).toBeInstanceOf(File);
    expect((forwarded as File).name).toBe("fight-2026-07-07.zevtc");

    // The wizard auto-transitions from upload -> parse once the POST
    // resolves. Status badge defaults to "pending" (no GET yet).
    const parsePanel = await screen.findByTestId("step-parse");
    expect(parsePanel).toBeInTheDocument();
    expect(screen.getByTestId("parse-status")).toHaveTextContent("pending");
    expect(parsePanel).toHaveTextContent("11111111-2222-3333-4444-555555555555");
    expect(parsePanel).toHaveTextContent("abcdef01");
    expect(parsePanel).toHaveTextContent("6789");
  });

  it("advances to step 4 (done) when the poll resolves completed (v0.9.0)", async () => {
    vi.mocked(uploadLog).mockResolvedValue({
      id: "22222222-3333-4444-5555-666666666666",
      sha256: "deadbeefcafebabe".repeat(4),
      status: "pending",
    });
    vi.mocked(fetchUploadStatus).mockResolvedValue({
      id: "22222222-3333-4444-5555-666666666666",
      sha256: "deadbeefcafebabe".repeat(4),
      original_filename: "fight-2026-07-07.zevtc",
      size_bytes: 4096,
      uploaded_at: "2026-07-09T12:00:00Z",
      status: "completed",
      error_message: null,
      parser_version: "v1.0.0",
      fight_id: "fight-deadbeef",
    });
    render(<UploadPage />);
    fireEvent.change(screen.getByTestId("file-input") as HTMLInputElement, {
      target: { files: [makeFile("fight-2026-07-07.zevtc")] },
    });
    fireEvent.click(screen.getByTestId("next"));

    const done = await screen.findByTestId("step-done");
    expect(done).toHaveTextContent("Upload complete");
    expect(done).toHaveTextContent("completed");
    const link = done.querySelector("a");
    expect(link).toHaveAttribute("href", "/fights/fight-deadbeef");
    expect(link).toHaveTextContent("/fights/fight-deadbeef");
  });

  it("formats real ApiError failures from POST as Upstream error (v0.9.0)", async () => {
    vi.mocked(uploadLog).mockRejectedValueOnce(
      new ApiError(502, "upstream gateway"),
    );
    render(<UploadPage />);
    fireEvent.change(screen.getByTestId("file-input") as HTMLInputElement, {
      target: { files: [makeFile("fight.zevtc")] },
    });
    fireEvent.click(screen.getByTestId("next"));

    // The wizard stays on step 2 (upload) and now exposes the error
    // banner so the analyst sees the same message format as the
    // legacy page did.
    const errorMsg = await screen.findByTestId("error");
    expect(errorMsg).toHaveTextContent(
      "Upstream error: 502: 502: upstream gateway",
    );
    expect(screen.getByTestId("step-upload")).toBeInTheDocument();
  });

  it("resets back to step 1 when 'Upload another' fires (v0.9.0)", async () => {
    vi.mocked(uploadLog).mockResolvedValue({
      id: "22222222-3333-4444-5555-666666666666",
      sha256: "deadbeefcafebabe".repeat(4),
      status: "pending",
    });
    vi.mocked(fetchUploadStatus).mockResolvedValue({
      id: "22222222-3333-4444-5555-666666666666",
      sha256: "deadbeefcafebabe".repeat(4),
      original_filename: "fight-2026-07-07.zevtc",
      size_bytes: 4096,
      uploaded_at: "2026-07-09T12:00:00Z",
      status: "completed",
      error_message: null,
      parser_version: "v1.0.0",
      fight_id: "fight-deadbeef",
    });
    render(<UploadPage />);
    fireEvent.change(screen.getByTestId("file-input") as HTMLInputElement, {
      target: { files: [makeFile("fight-2026-07-07.zevtc")] },
    });
    fireEvent.click(screen.getByTestId("next"));
    await screen.findByTestId("step-done");

    fireEvent.click(screen.getByTestId("upload-another"));
    expect(screen.getByTestId("step-pick")).toBeInTheDocument();
    expect(screen.queryByTestId("step-done")).not.toBeInTheDocument();
  });

  it("formats real ApiError failures from network layer (v0.9.0)", async () => {
    vi.mocked(uploadLog).mockRejectedValueOnce(
      new Error("Network unreachable"),
    );
    render(<UploadPage />);
    fireEvent.change(screen.getByTestId("file-input") as HTMLInputElement, {
      target: { files: [makeFile("fight.zevtc")] },
    });
    fireEvent.click(screen.getByTestId("next"));

    const errorMsg = await screen.findByTestId("error");
    expect(errorMsg).toHaveTextContent("Network unreachable");
    expect(screen.getByTestId("step-upload")).toBeInTheDocument();
  });
});

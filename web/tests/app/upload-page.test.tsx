import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";

/**
 * Vitest partial mock: keep the real ``ApiError`` + ``formatApiError``
 * surface so the page tests against the actual error class. We only
 * stub ``uploadLog`` (the network surface). If the real ``ApiError``
 * constructor gains fields, the test still validates against the
 * real class -- the mock cannot silently drift.
 */
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, uploadLog: vi.fn() };
});

import UploadPage from "@/app/upload/page";
import { ApiError, uploadLog } from "@/lib/api";

/**
 * CI smoke for the upload page.
 *
 * Like ``fights-page.test.tsx`` this is a deliberate mock-and-call
 * smoke (no real multipart upload, no Next.js RSC runtime), so the
 * assertions cover: (1) the empty-state contract, (2) the
 * client-side extension guard, (3) the happy-path card render with
 * a real ``UploadCreatedRow``, (4) the ``ApiError`` formatting via
 * the shared ``formatApiError`` helper, and (5) network-failure
 * fall-through. If the page grows to use streaming SSR / cookies,
 * this test must move alongside the page (refactor into a Client
 * Component wrapper if needed).
 */
function makeFile(name = "fight-2026-07-07.zevtc", bytes = 4096): File {
  const blob = new Blob([new Uint8Array(bytes)], {
    type: "application/octet-stream",
  });
  return new File([blob], name, { type: "application/octet-stream" });
}

describe("UploadPage", () => {
  it("renders the heading + empty file chip + disabled submit", () => {
    render(<UploadPage />);
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /Upload a .zevtc replay/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("file-chip")).toHaveTextContent(
      "No file selected",
    );
    expect(screen.getByTestId("submit")).toBeDisabled();
  });

  it("rejects non-.zevtc files before uploading", () => {
    render(<UploadPage />);
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile("evil.exe")] } });
    expect(uploadLog).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Only .zevtc files are accepted.",
    );
    expect(screen.getByTestId("submit")).toBeDisabled();
  });

  it("uploads a valid .zevtc and renders the result card", async () => {
    vi.mocked(uploadLog).mockResolvedValue({
      id: "11111111-2222-3333-4444-555555555555",
      sha256: "abcdef0123456789".repeat(4),
      status: "pending",
    });
    render(<UploadPage />);
    const input = screen.getByTestId("file-input") as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [makeFile("fight-2026-07-07.zevtc")] },
    });
    fireEvent.click(screen.getByTestId("submit"));

    await waitFor(() => expect(uploadLog).toHaveBeenCalledTimes(1));
    const forwarded = vi.mocked(uploadLog).mock.calls[0]?.[0];
    expect(forwarded).toBeInstanceOf(File);
    expect((forwarded as File).name).toBe("fight-2026-07-07.zevtc");

    const card = await screen.findByTestId("result");
    expect(card).toHaveTextContent("Upload received");
    expect(card).toHaveTextContent("11111111-2222-3333-4444-555555555555");
    expect(card).toHaveTextContent("abcdef01");
    expect(card).toHaveTextContent("6789");
    expect(card).toHaveTextContent("pending");
  });

  it("formats real ApiError failures as Upstream error: status: message", async () => {
    // Uses the REAL ApiError class (partial mock preserved it). The
    // assertion is a literal string so the test fails on any drift
    // in formatApiError or the ApiError ctor signature.
    vi.mocked(uploadLog).mockRejectedValueOnce(
      new ApiError(502, "upstream gateway"),
    );
    render(<UploadPage />);
    fireEvent.change(screen.getByTestId("file-input") as HTMLInputElement, {
      target: { files: [makeFile("fight.zevtc")] },
    });
    fireEvent.click(screen.getByTestId("submit"));

    expect(await screen.findByTestId("error")).toHaveTextContent(
      "Upstream error: 502: 502: upstream gateway",
    );
  });

  it("passes through network failures as the thrown Error message", async () => {
    vi.mocked(uploadLog).mockRejectedValueOnce(
      new Error("Network unreachable"),
    );
    render(<UploadPage />);
    fireEvent.change(screen.getByTestId("file-input") as HTMLInputElement, {
      target: { files: [makeFile("fight.zevtc")] },
    });
    fireEvent.click(screen.getByTestId("submit"));

    const errorMsg = await screen.findByTestId("error");
    expect(errorMsg).toHaveTextContent("Network unreachable");
  });
});

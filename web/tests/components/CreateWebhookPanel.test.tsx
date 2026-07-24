import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: vi.fn(),
  }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  // Import the real module so we keep formatApiError's behaviour
  // for the inline error path. We only mock createWebhook to
  // observe the wiring (URL + description + filter JSON + the
  // 201 -> reveal transition).
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    createWebhook: vi.fn(),
  };
});

import { CreateWebhookPanel } from "@/components/CreateWebhookPanel";
import { createWebhook } from "@/lib/api";

describe("CreateWebhookPanel", () => {
  beforeEach(() => {
    vi.mocked(createWebhook).mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function changeValue(testId: string, value: string) {
    fireEvent.change(screen.getByTestId(testId), { target: { value } });
  }

  it("renders the closed-phase trigger initially", () => {
    render(<CreateWebhookPanel />);
    expect(
      screen.getByTestId("create-webhook-open"),
    ).toBeInTheDocument();
  });

  it("opens the form when the trigger is clicked", () => {
    render(<CreateWebhookPanel />);
    fireEvent.click(screen.getByTestId("create-webhook-open"));
    expect(screen.getByTestId("create-webhook-form")).toBeInTheDocument();
    expect(screen.getByTestId("create-webhook-url")).toBeInTheDocument();
    expect(screen.getByTestId("create-webhook-description")).toBeInTheDocument();
    expect(screen.getByTestId("create-webhook-filter")).toBeInTheDocument();
  });

  it("submits with explicit filter, transitions to reveal, and shows the one-shot secret", async () => {
    vi.mocked(createWebhook).mockResolvedValueOnce({
      id: "whsub_xyz789",
      url: "https://example.com/wh",
      description: "smoke",
      filter: { kind: "upload_completed" },
      created_at: "2026-07-15T00:00:00+00:00",
      secret: "whsec_DEMO_PLAINTEXT_32B",
    });
    render(<CreateWebhookPanel />);
    fireEvent.click(screen.getByTestId("create-webhook-open"));
    changeValue("create-webhook-url", "https://example.com/wh");
    changeValue("create-webhook-description", "smoke");
    changeValue(
      "create-webhook-filter",
      '{"kind": "upload_completed"}',
    );
    fireEvent.click(screen.getByTestId("create-webhook-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("create-webhook-reveal")).toBeInTheDocument();
    });
    expect(screen.getByTestId("create-webhook-secret")).toHaveTextContent(
      "whsec_DEMO_PLAINTEXT_32B",
    );
    // Done button is disabled until the ack checkbox is ticked.
    expect(screen.getByTestId("create-webhook-done")).toBeDisabled();

    fireEvent.click(screen.getByTestId("create-webhook-ack"));
    expect(screen.getByTestId("create-webhook-done")).not.toBeDisabled();

    // createWebhook received the parsed filter object, not the
    // raw textarea string.
    expect(createWebhook).toHaveBeenCalledWith({
      url: "https://example.com/wh",
      description: "smoke",
      filter: { kind: "upload_completed" },
    });
  });

  it("defaults filter to {kind: upload_completed} when the field is empty", async () => {
    // Confirms the form's UX promise: "leave empty for default"
    // actually produces a filter the backend accepts, instead of
    // 422-ing with ``filter.kind is required``.
    vi.mocked(createWebhook).mockResolvedValueOnce({
      id: "whsub_default",
      url: "https://example.com/wh",
      description: null,
      filter: { kind: "upload_completed" },
      created_at: "2026-07-15T00:00:00+00:00",
      secret: "whsec_DEFAULT",
    });
    render(<CreateWebhookPanel />);
    fireEvent.click(screen.getByTestId("create-webhook-open"));
    changeValue("create-webhook-url", "https://example.com/wh");
    // Filter field is left blank.
    fireEvent.click(screen.getByTestId("create-webhook-submit"));
    await waitFor(() => {
      expect(createWebhook).toHaveBeenCalledWith({
        url: "https://example.com/wh",
        description: null,
        filter: { kind: "upload_completed" },
      });
    });
  });

  it("keeps the submit button disabled when the URL is empty", () => {
    render(<CreateWebhookPanel />);
    fireEvent.click(screen.getByTestId("create-webhook-open"));
    // Without any URL the form is !canSubmit, so the submit
    // button is disabled and createWebhook is never invoked.
    expect(screen.getByTestId("create-webhook-submit")).toBeDisabled();
    fireEvent.click(screen.getByTestId("create-webhook-submit"));
    expect(createWebhook).not.toHaveBeenCalled();
  });

  it("renders an inline error when the filter JSON is malformed", async () => {
    render(<CreateWebhookPanel />);
    fireEvent.click(screen.getByTestId("create-webhook-open"));
    changeValue("create-webhook-url", "https://example.com/wh");
    changeValue("create-webhook-filter", "not json {");
    fireEvent.click(screen.getByTestId("create-webhook-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("create-webhook-error")).toBeInTheDocument();
    });
  });

  it("surfaces backend errors from createWebhook rejections", async () => {
    vi.mocked(createWebhook).mockRejectedValueOnce(
      new Error("422: webhook url resolves to a private address"),
    );
    render(<CreateWebhookPanel />);
    fireEvent.click(screen.getByTestId("create-webhook-open"));
    changeValue("create-webhook-url", "https://10.0.0.1/wh");
    fireEvent.click(screen.getByTestId("create-webhook-submit"));
    await waitFor(() => {
      expect(screen.getByTestId("create-webhook-error")).toHaveTextContent(
        /private address/i,
      );
    });
  });
});

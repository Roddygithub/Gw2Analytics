import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchWebhookDeliveries: vi.fn(),
  fetchWebhookSubscriptions: vi.fn(),
  // Mocked here so the page-component's \`formatApiError\`
  // call in the catch branch of \`Promise.allSettled\`
  // resolves to a deterministic string instead of an
  // "upstream gateway" leak from the real implementation.
  formatApiError: vi.fn((err: unknown) =>
    err instanceof Error ? `Error: ${err.message}` : "Error: unknown",
  ),
}));

vi.mock("@/components/WebhookDlqGrid", () => ({
  WebhookDlqGrid: ({ rows }: { rows: unknown[] }) => (
    <div data-testid="webhook-dlq-grid">{rows.length} rows</div>
  ),
}));

vi.mock("@/components/WebhookSubscriptionsGrid", () => ({
  WebhookSubscriptionsGrid: ({ rows }: { rows: unknown[] }) => (
    <div data-testid="webhook-subscriptions-grid">{rows.length} rows</div>
  ),
}));

vi.mock("@/components/CreateWebhookPanel", () => ({
  CreateWebhookPanel: () => (
    <div data-testid="create-webhook-panel">create webhook panel</div>
  ),
}));

import WebhooksPage from "@/app/webhooks/page";
import {
  fetchWebhookDeliveries,
  fetchWebhookSubscriptions,
} from "@/lib/api";

describe("WebhooksPage", () => {
  beforeEach(() => {
    vi.mocked(fetchWebhookDeliveries).mockReset();
    vi.mocked(fetchWebhookSubscriptions).mockReset();
  });

  it("renders both Subscriptions and DLQ sections when both fetches resolve", async () => {
    vi.mocked(fetchWebhookDeliveries).mockResolvedValueOnce([]);
    vi.mocked(fetchWebhookSubscriptions).mockResolvedValueOnce([]);
    const tree = await WebhooksPage();
    render(tree);
    expect(
      screen.getByRole("heading", { level: 1, name: "Webhooks" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: "Subscriptions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "DLQ (failed deliveries)",
      }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("webhook-subscriptions-grid")).toBeInTheDocument();
    expect(screen.getByTestId("webhook-dlq-grid")).toBeInTheDocument();
    expect(screen.getByTestId("create-webhook-panel")).toBeInTheDocument();
  });

  it("renders only the Subscriptions error card when DLQ fetch rejects", async () => {
    vi.mocked(fetchWebhookDeliveries).mockRejectedValueOnce(
      new Error("502: upstream gateway"),
    );
    vi.mocked(fetchWebhookSubscriptions).mockResolvedValueOnce([]);
    const tree = await WebhooksPage();
    render(tree);
    expect(
      screen.getByText(/Error: 502: upstream gateway/),
    ).toBeInTheDocument();
    // The Subscriptions section still renders: DLQ error is
    // surfaced under the DLQ subheader, not propagated as a
    // full-page error.
    expect(screen.getByTestId("webhook-subscriptions-grid")).toBeInTheDocument();
  });

  it("renders only the DLQ error card when Subscriptions fetch rejects", async () => {
    vi.mocked(fetchWebhookDeliveries).mockResolvedValueOnce([]);
    vi.mocked(fetchWebhookSubscriptions).mockRejectedValueOnce(
      new Error("500: subscriptions gateway"),
    );
    const tree = await WebhooksPage();
    render(tree);
    expect(
      screen.getByText(/Error: 500: subscriptions gateway/),
    ).toBeInTheDocument();
    expect(screen.getByTestId("webhook-dlq-grid")).toBeInTheDocument();
  });

  it("renders the Subscriptions grid with rows + the DLQ grid with rows", async () => {
    vi.mocked(fetchWebhookDeliveries).mockResolvedValueOnce([
      {
        id: "dly_abc123",
        subscription_id: "whsub_abc123",
        upload_id: "upload-1",
        last_error: "non-2xx response: 500",
        moved_to_dlq_at: "2026-07-08T00:00:00+00:00",
      },
    ]);
    vi.mocked(fetchWebhookSubscriptions).mockResolvedValueOnce([
      {
        id: "whsub_xyz789",
        url: "https://example.com/webhook",
        description: "CI smoke tests",
        filter: { upload_status: "completed" },
        created_at: "2026-07-15T00:00:00+00:00",
      },
    ]);
    const tree = await WebhooksPage();
    render(tree);
    expect(screen.getByTestId("webhook-subscriptions-grid")).toHaveTextContent(
      "1 rows",
    );
    expect(screen.getByTestId("webhook-dlq-grid")).toHaveTextContent("1 rows");
  });
});

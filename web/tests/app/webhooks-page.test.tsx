import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchWebhookDeliveries: vi.fn(),
}));

vi.mock("@/components/WebhookDlqGrid", () => ({
  WebhookDlqGrid: ({ rows }: { rows: unknown[] }) => (
    <div data-testid="webhook-dlq-grid">{rows.length} rows</div>
  ),
}));

import WebhooksPage from "@/app/webhooks/page";
import { fetchWebhookDeliveries } from "@/lib/api";

describe("WebhooksPage", () => {
  beforeEach(() => {
    vi.mocked(fetchWebhookDeliveries).mockReset();
  });

  it("renders the grid when there are no failed deliveries", async () => {
    vi.mocked(fetchWebhookDeliveries).mockResolvedValueOnce([]);
    const tree = await WebhooksPage();
    render(tree);
    expect(screen.getByRole("heading", { name: "Webhook DLQ" })).toBeInTheDocument();
    expect(screen.getByTestId("webhook-dlq-grid")).toBeInTheDocument();
  });

  it("renders the upstream-error card when fetchWebhookDeliveries throws", async () => {
    vi.mocked(fetchWebhookDeliveries).mockRejectedValueOnce(new Error("502: upstream gateway"));
    const tree = await WebhooksPage();
    render(tree);
    expect(screen.getByText("Error: 502: upstream gateway")).toBeInTheDocument();
  });

  it("renders the grid when deliveries are present", async () => {
    vi.mocked(fetchWebhookDeliveries).mockResolvedValueOnce([
      {
        id: "dly_abc123",
        subscription_id: "whsub_abc123",
        upload_id: "upload-1",
        last_error: "non-2xx response: 500",
        moved_to_dlq_at: "2026-07-08T00:00:00+00:00",
      },
    ]);
    const tree = await WebhooksPage();
    render(tree);
    expect(screen.getByRole("heading", { name: "Webhook DLQ" })).toBeInTheDocument();
    expect(screen.getByTestId("webhook-dlq-grid")).toBeInTheDocument();
  });
});

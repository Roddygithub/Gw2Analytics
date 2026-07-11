import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";

const refreshMock = vi.fn();

vi.mock("@/lib/api", () => ({
  replayDlq: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: refreshMock }),
}));

beforeAll(() => {
  vi.doMock("ag-grid-react", () => ({
    AgGridReact: function MockAgGridReact<T extends Record<string, unknown>>({
      rowData,
      columnDefs,
    }: {
      rowData?: T[];
      columnDefs?: {
        field?: keyof T;
        headerName?: string;
        cellRenderer?: (params: { data: T }) => React.ReactNode;
      }[];
    }) {
      return (
        <table>
          <tbody>
            {rowData?.map((row, rowIdx) => (
              <tr key={rowIdx}>
                {columnDefs?.map((col, colIdx) => (
                  <td key={colIdx}>
                    {col.cellRenderer
                      ? col.cellRenderer({ data: row })
                      : String((row[col.field as keyof T] as unknown) ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    },
  }));
});

import { replayDlq } from "@/lib/api";

const ROWS = [
  {
    id: "dly_abc123",
    subscription_id: "whsub_abc123",
    upload_id: "upload-1",
    last_error: "non-2xx response: 500",
    moved_to_dlq_at: "2026-07-08T00:00:00+00:00",
  },
];

describe("WebhookDlqGrid", () => {
  beforeEach(() => {
    vi.mocked(replayDlq).mockReset();
    refreshMock.mockReset();
  });

  it("renders rows and a Replay button per row", async () => {
    const { WebhookDlqGrid } = await import("@/components/WebhookDlqGrid");
    render(<WebhookDlqGrid rows={ROWS} />);
    expect(screen.getByText("dly_abc123")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replay" })).toBeInTheDocument();
  });

  it("calls replayDlq and refreshes the page when Replay is clicked", async () => {
    vi.mocked(replayDlq).mockResolvedValueOnce(undefined);
    const { WebhookDlqGrid } = await import("@/components/WebhookDlqGrid");
    render(<WebhookDlqGrid rows={ROWS} />);
    const button = screen.getByRole("button", { name: "Replay" });
    fireEvent.click(button);
    await waitFor(() => {
      expect(replayDlq).toHaveBeenCalledWith("dly_abc123");
      expect(refreshMock).toHaveBeenCalled();
    });
  });

  it("renders empty state when no rows are provided", async () => {
    const { WebhookDlqGrid } = await import("@/components/WebhookDlqGrid");
    render(<WebhookDlqGrid rows={[]} />);
    expect(screen.queryByText("dly_abc123")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Replay" })).not.toBeInTheDocument();
    expect(screen.getByText("No failed deliveries.")).toBeInTheDocument();
  });
});

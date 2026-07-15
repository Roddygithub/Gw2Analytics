import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CsvDownloadButton } from "@/components/CsvDownloadButton";
import type { CsvColumn } from "@/lib/csv";
import * as csvModule from "@/lib/csv";

vi.mock("@/lib/csv", () => ({
  toCsv: vi.fn(() => "csv-content"),
  downloadCsv: vi.fn(),
}));

interface Row {
  id: number;
  name: string;
}

const columns: CsvColumn<Row>[] = [
  { field: "id", headerName: "ID" },
  { field: "name", headerName: "Name" },
];

describe("CsvDownloadButton", () => {
  it("renders nothing when rows is empty", () => {
    const { container } = render(
      <CsvDownloadButton<Row> rows={[]} columns={columns} filename="test.csv" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the default button label", () => {
    render(
      <CsvDownloadButton<Row>
        rows={[{ id: 1, name: "A" }]}
        columns={columns}
        filename="test.csv"
      />,
    );
    expect(screen.getByRole("button", { name: "Download CSV" })).toBeInTheDocument();
  });

  it("renders a custom button label", () => {
    render(
      <CsvDownloadButton<Row>
        rows={[{ id: 1, name: "A" }]}
        columns={columns}
        filename="test.csv"
        label="Export"
      />,
    );
    expect(screen.getByRole("button", { name: "Export" })).toBeInTheDocument();
  });

  it("calls toCsv and downloadCsv on click", async () => {
    const rows = [{ id: 1, name: "A" }];
    render(
      <CsvDownloadButton<Row>
        rows={rows}
        columns={columns}
        filename="players.csv"
      />,
    );

    fireEvent.click(screen.getByRole("button"));

    expect(csvModule.toCsv).toHaveBeenCalledWith(rows, columns);
    expect(csvModule.downloadCsv).toHaveBeenCalledWith("players.csv", "csv-content");
  });
});

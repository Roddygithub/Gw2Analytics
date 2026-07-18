"use client";
import React from "react";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AgGridReact } from "ag-grid-react";
import { type ColDef, type ICellRendererParams } from "ag-grid-community";
import type { WebhookDlqRow } from "@/lib/api";
import { replayDlq } from "@/lib/api";

import { appGridTheme } from "./ag-grid-setup";
import styles from "./WebhookDlqGrid.module.css";

const GRID_CONTAINER_STYLE: React.CSSProperties = {
  height: 600,
  width: "100%",
};

function formatDate(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function WebhookDlqGrid({ rows }: { rows: WebhookDlqRow[] }) {
  const router = useRouter();
  const [replaying, setReplaying] = useState<Set<string>>(new Set());

  const columnDefs = useMemo<ColDef<WebhookDlqRow>[]>(
    () => [
      {
        field: "id",
        headerName: "Delivery ID",
        sortable: true,
        filter: true,
        minWidth: 240,
      },
      {
        field: "subscription_id",
        headerName: "Subscription",
        sortable: true,
        filter: true,
        minWidth: 240,
      },
      {
        field: "upload_id",
        headerName: "Upload",
        sortable: true,
        filter: true,
        minWidth: 240,
      },
      {
        field: "last_error",
        headerName: "Last error",
        sortable: true,
        filter: true,
        minWidth: 200,
        valueFormatter: (p) => p.value ?? "—",
      },
      {
        field: "moved_to_dlq_at",
        headerName: "Moved to DLQ",
        sortable: true,
        filter: true,
        minWidth: 180,
        valueFormatter: (p) => formatDate(p.value),
      },
      {
        headerName: "Actions",
        sortable: false,
        filter: false,
        minWidth: 120,
        cellRenderer: (params: ICellRendererParams<WebhookDlqRow>) => {
          const id = params.data?.id;
          if (!id) {
            return null;
          }
          const busy = replaying.has(id);
          return (
            <button
              type="button"
              disabled={busy}
              onClick={async () => {
                setReplaying((prev) => new Set(prev).add(id));
                try {
                  await replayDlq(id);
                  router.refresh();
                } finally {
                  setReplaying((prev) => {
                    const next = new Set(prev);
                    next.delete(id);
                    return next;
                  });
                }
              }}
              className={styles.replayButton}
            >
              {busy ? "Replaying…" : "Replay"}
            </button>
          );
        },
      },
    ],
    [replaying, router],
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({
      resizable: true,
    }),
    [],
  );

  if (rows.length === 0) {
    return <div className={styles.emptyState}>No failed deliveries.</div>;
  }

  return (
    <div style={GRID_CONTAINER_STYLE}>
      <AgGridReact<WebhookDlqRow>
        theme={appGridTheme}
        rowData={rows}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        pagination
        paginationPageSize={25}
        paginationPageSizeSelector={false}
        animateRows
      />
    </div>
  );
}

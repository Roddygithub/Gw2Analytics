/**
 * WebhookSubscriptionsGrid — AG-Grid table for active webhook
 * subscriptions. Mirrors :class:\`WebhookDlqGrid\` (same
 * \`appGridTheme\` + \`AgGridReact\` + \`gridOptions\` pattern) so
 * the operator's mental model of the /webhooks page is a single
 * table-style surface. The \`Actions\` column renders a per-row
 * \`Revoke\` button that delegates to
 * :func:\`revokeWebhook\` + \`router.refresh\` so the server
 * component re-fetches both the subscriptions list + the DLQ
 * (the latter is unaffected but the refresh is the cheapest
 * way to keep the two arrays in lockstep after a mutation).
 */

"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AgGridReact } from "ag-grid-react";
import { type ColDef, type ICellRendererParams } from "ag-grid-community";
import { type WebhookSubscriptionRow } from "@/lib/api";
import { revokeWebhook } from "@/lib/api";
import { formatApiError } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

import { appGridTheme } from "./ag-grid-setup";
import styles from "./WebhookSubscriptionsGrid.module.css";

const GRID_CONTAINER_STYLE = {
  height: 600,
  width: "100%",
} as const;

function summariseFilter(
  filter: WebhookSubscriptionRow["filter"],
): string {
  if (!filter || Object.keys(filter).length === 0) {
    return "all events";
  }
  // Operators want the filter contract at a glance — render
  // a stable, key-sorted key=value list so the same filter
  // shape always produces the same row text.
  return Object.keys(filter)
    .sort()
    .map((k) => `${k}=${JSON.stringify(filter[k])}`)
    .join(", ");
}

export function WebhookSubscriptionsGrid({
  rows,
}: {
  rows: WebhookSubscriptionRow[];
}) {
  const router = useRouter();
  const [revoking, setRevoking] = useState<Set<string>>(new Set());
  const [rowError, setRowError] = useState<string | null>(null);

  const columnDefs = useMemo<ColDef<WebhookSubscriptionRow>[]>(
    () => [
      {
        field: "id",
        headerName: "ID",
        sortable: true,
        filter: true,
        minWidth: 240,
      },
      {
        field: "url",
        headerName: "URL",
        sortable: true,
        filter: true,
        minWidth: 280,
      },
      {
        field: "description",
        headerName: "Description",
        sortable: true,
        filter: true,
        minWidth: 180,
        valueFormatter: (p) => p.value ?? "—",
      },
      {
        field: "filter",
        headerName: "Filter",
        sortable: true,
        filter: true,
        minWidth: 220,
        valueFormatter: (p) => summariseFilter(p.value),
      },
      {
        field: "created_at",
        headerName: "Created at",
        sortable: true,
        filter: true,
        minWidth: 180,
        valueFormatter: (p) => formatDateTime(p.value),
      },
      {
        headerName: "Actions",
        sortable: false,
        filter: false,
        minWidth: 130,
        cellRenderer: (params: ICellRendererParams<WebhookSubscriptionRow>) => {
          const id = params.data?.id;
          if (!id) {
            return null;
          }
          const busy = revoking.has(id);
          return (
            <button
              type="button"
              disabled={busy}
              onClick={async () => {
                setRowError(null);
                setRevoking((prev) => new Set(prev).add(id));
                try {
                  await revokeWebhook(id);
                  router.refresh();
                } catch (err) {
                  setRowError(formatApiError(err));
                } finally {
                  setRevoking((prev) => {
                    const next = new Set(prev);
                    next.delete(id);
                    return next;
                  });
                }
              }}
              className={styles.revokeButton}
              data-testid={`revoke-${id}`}
            >
              {busy ? "Revoking…" : "Revoke"}
            </button>
          );
        },
      },
    ],
    [revoking, router],
  );

  const defaultColDef = useMemo<ColDef>(
    () => ({
      resizable: true,
    }),
    [],
  );

  // The revoke-failure error renders above BOTH the empty state
  // and the populated grid so the analyst sees the failure cause
  // before the row context. Branching in the JSX keeps the order
  // unified across the two cases (no asymmetric "see the error
  // below the empty card" surprise).
  const errorNode =
    rowError !== null ? (
      <p className={styles.error} role="alert">
        Revoke failed: {rowError}
      </p>
    ) : null;

  if (rows.length === 0) {
    return (
      <>
        {errorNode}
        <div className={styles.emptyState} data-testid="webhook-subscriptions-empty">
          No webhook subscriptions yet. Click <strong>+ New subscription</strong>{" "}
          above to register one.
        </div>
      </>
    );
  }

  return (
    <>
      {errorNode}
      <div style={GRID_CONTAINER_STYLE}>
        <AgGridReact<WebhookSubscriptionRow>
          theme={appGridTheme}
          rowData={rows}
          columnDefs={columnDefs}
          defaultColDef={defaultColDef}
          pagination
          paginationPageSize={25}
          paginationPageSizeSelector={false}
          getRowId={(params) => params.data.id}
          animateRows
        />
      </div>
    </>
  );
}

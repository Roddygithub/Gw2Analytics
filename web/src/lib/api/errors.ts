import { UPSTREAM_ERROR_PREFIX } from "@/lib/copy/error-messages";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly error_code?: string,
  ) {
    super(message);
  }
}

export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    return `${UPSTREAM_ERROR_PREFIX}${err.status}: ${err.message}`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return String(err);
}

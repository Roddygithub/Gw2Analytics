export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(`${status}: ${message}`);
  }
}

export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    return `Upstream error: ${err.status}: ${err.message}`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return String(err);
}

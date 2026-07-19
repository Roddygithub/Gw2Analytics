/**
 * Convert a file path into a safe string usable in screenshot names and
 * test step titles. Replaces path separators, spaces, and special
 * characters with underscores and truncates to avoid filesystem limits.
 * Falls back to "file" if the sanitized result is empty.
 */
export function safeFileLabel(filePath: string): string {
  const base = filePath.split("/").pop() ?? filePath;
  const sanitized = base
    .replace(/[^a-zA-Z0-9._-]+/g, "_")
    .replace(/_{2,}/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
  return sanitized || "file";
}

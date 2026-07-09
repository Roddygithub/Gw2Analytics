/**
 * v0.10.0 plan 032: shared IANA timezone catalog for the
 * day-bucketed timeline selectors.
 *
 * Extracted from the local ``TIMEZONE_OPTIONS`` const in
 * :class:`PlayerTimelineSection` so the
 * :class:`CrossAccountCompareSection` (plan 032) and the
 * existing per-account section (v0.8.9) ship the SAME 25
 * curated IANA zones. Pre-plan-032 the compare section
 * had a hand-picked 9-zone subset; the analyst who has
 * used the per-account page and switches to the compare
 * view would silently lose the 16 missing zones.
 *
 * Why a 25-city curated list (not the full IANA database)
 * =======================================================
 * The full IANA database has ~400 zones; rendering all of
 * them in a native ``<select>`` is overwhelming for the
 * analyst. The 25-zone list covers the 99% use case (UTC
 * + the 8 major US TZ + 8 EU TZ + 5 APAC + AU + NZ + 1
 * African + 1 South American). A v0.10.X followup could
 * lift this to a typeahead-combobox if the curated list
 * becomes a friction point.
 */

export interface TimezoneOption {
  value: string;
  label: string;
  /**
   * v0.10.0 plan 032: optional short label for the
   * cross-account compare section's TZ dropdown. The
   * compare dropdown sits in a denser UI cluster
   * (metric + scale + bucket + tz + chips all on one
   * row) so the long-form labels would render ~30%
   * wider than the surrounding buttons. The per-account
   * section has more horizontal room (its controls are
   * spread across the section header) so it keeps the
   * long form. When ``shortLabel`` is ``undefined``
   * (the default), the consumer falls back to
   * ``label``. Only the 4 US zones have a short form
   * today (the "City" suffix is redundant in the
   * compare context where the analyst is comparing
   * accounts not browsing TZ catalogs).
   */
  shortLabel?: string;
}

export const TIMEZONE_OPTIONS: ReadonlyArray<TimezoneOption> = [
  { value: "UTC", label: "UTC" },
  {
    value: "America/New_York",
    label: "US Eastern (New York)",
    shortLabel: "US Eastern",
  },
  {
    value: "America/Chicago",
    label: "US Central (Chicago)",
    shortLabel: "US Central",
  },
  {
    value: "America/Denver",
    label: "US Mountain (Denver)",
    shortLabel: "US Mountain",
  },
  {
    value: "America/Los_Angeles",
    label: "US Pacific (Los Angeles)",
    shortLabel: "US Pacific",
  },
  { value: "America/Sao_Paulo", label: "BR São Paulo" },
  { value: "Europe/London", label: "UK London" },
  { value: "Europe/Paris", label: "EU Paris" },
  { value: "Europe/Berlin", label: "EU Berlin" },
  { value: "Europe/Madrid", label: "EU Madrid" },
  { value: "Europe/Rome", label: "EU Rome" },
  { value: "Europe/Warsaw", label: "PL Warsaw" },
  { value: "Europe/Stockholm", label: "SE Stockholm" },
  { value: "Europe/Moscow", label: "RU Moscow" },
  { value: "Africa/Cairo", label: "EG Cairo" },
  { value: "Africa/Johannesburg", label: "ZA Johannesburg" },
  { value: "Asia/Dubai", label: "AE Dubai" },
  { value: "Asia/Kolkata", label: "IN Kolkata" },
  { value: "Asia/Singapore", label: "SG Singapore" },
  { value: "Asia/Shanghai", label: "CN Shanghai" },
  { value: "Asia/Seoul", label: "KR Seoul" },
  { value: "Asia/Tokyo", label: "JP Tokyo" },
  { value: "Australia/Perth", label: "AU Perth" },
  { value: "Australia/Sydney", label: "AU Sydney" },
  { value: "Pacific/Auckland", label: "NZ Auckland" },
];

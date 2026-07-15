/**
 * GW2Analytics logo.
 *
 * An isometric layered diamond evoking WvW objectives / map layers,
 * rendered in the GW2Mists accent orange against the dark theme.
 */
export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path d="M12 2L2 7L12 12L22 7L12 2Z" fill="var(--accent)" />
      <path
        d="M2 17L12 22L22 17M2 12L12 17L22 12"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/**
 * Thesis logo mark — "The Vanishing Point"
 *
 * Two perspective lines converging toward a luminous focal point.
 * "Clear Horizon" palette:
 * - Lines use Mist-400 (#A8A29E) — visible on light backgrounds
 * - Dot uses Rose-600 (#A94E80) — brand accent
 */
export function BrierLogoMark({
  size = 28,
  className = "",
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Thesis"
    >
      {/* Glow halo — rose at low opacity */}
      <circle
        cx="21.5"
        cy="14"
        r="5.5"
        fill="#A94E80"
        opacity="0.10"
      />
      {/* Upper perspective rail */}
      <line
        x1="2"
        y1="4.5"
        x2="17"
        y2="12"
        stroke="#A8A29E"
        strokeWidth="1.2"
        strokeLinecap="round"
        opacity="0.55"
      />
      {/* Lower perspective rail */}
      <line
        x1="2"
        y1="23.5"
        x2="17"
        y2="16"
        stroke="#A8A29E"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.65"
      />
      {/* Focal point — Rose-600 vanishing point */}
      <circle cx="21.5" cy="14" r="3.2" fill="#A94E80" />
    </svg>
  );
}

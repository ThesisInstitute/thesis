import Link from "next/link";
import { COUNTRY_LABEL, TYPE_LABEL } from "@/data/forecast-cells";
import type { ForecastListingItem } from "@/data/forecast-listing";

const typeBadgeClass: Record<ForecastListingItem["type"], string> = {
  data: "bg-[var(--color-mist-100)] text-[var(--color-horizon-700)] border-[var(--color-mist-200)]",
  policy:
    "bg-[var(--color-accent-subtle)] text-[var(--color-rose-700)] border-[var(--color-rose-100)]",
  conditional: "bg-[#FFF4DD] text-[#7A5C20] border-[#F2DCAF]",
};

export function ForecastCard({ forecast }: { forecast: ForecastListingItem }) {
  return (
    <Link
      href={`/${forecast.slug}`}
      className="group flex flex-col gap-4 rounded-xl border bg-[var(--theme-bg-elevated)] p-6 no-underline transition-all duration-200 hover:no-underline hover:translate-y-[-2px] hover:shadow-md"
      style={{ borderColor: "var(--theme-border)", color: "var(--theme-text)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          <Badge className={typeBadgeClass[forecast.type]}>
            {TYPE_LABEL[forecast.type]}
          </Badge>
          <Badge>{COUNTRY_LABEL[forecast.country]}</Badge>
          {forecast.status === "resolved" && (
            <Badge className="border-[var(--color-horizon-300)] bg-[var(--color-horizon-50)] text-[var(--color-horizon-700)]">
              Resolved
            </Badge>
          )}
          {forecast.overdue && <Badge>Overdue</Badge>}
        </div>
        <span className="[font-family:var(--font-mono)] text-[0.62rem] text-[var(--theme-text-dim)]">
          {resolutionVerb(forecast)}{" "}
          {formatResolutionLabel(forecast.resolutionDate)}
        </span>
      </div>
      <h3 className="[font-family:var(--font-display)] text-[1.05rem] font-semibold leading-[1.3] tracking-[-0.01em] text-[var(--theme-text)] group-hover:text-[var(--color-accent)] transition-colors">
        {forecast.title}
      </h3>
      {forecast.overdue && (
        // A forecast still pending after its date says why, in the
        // resolver's terms. The full sentence is on the forecast's page.
        <p className="-mt-1 text-[0.78rem] leading-[1.45] text-[var(--theme-text-muted)]">
          {forecast.overdue.reason}
        </p>
      )}
      <div className="mt-auto">
        <div className="mb-2 flex items-baseline justify-between">
          <span className="[font-family:var(--font-mono)] text-[0.62rem] uppercase tracking-[0.1em] text-[var(--theme-text-dim)]">
            forecast · 80% CI
          </span>
          <span className="[font-family:var(--font-display)] text-[1.15rem] font-semibold text-[var(--color-accent)]">
            {forecast.point.label}
          </span>
        </div>
        <CompactForecastViz forecast={forecast} />
      </div>
    </Link>
  );
}

/** "resolves" is a promise about the future; past the date it is wrong. */
export function resolutionVerb(
  forecast: Pick<ForecastListingItem, "status" | "overdue">,
): string {
  if (forecast.status === "resolved") return "resolved";
  return forecast.overdue ? "was due" : "resolves";
}

function Badge({
  children,
  className = "border-[var(--theme-border)] bg-[var(--theme-bg-surface)] text-[var(--theme-text-dim)]",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`inline-block rounded-full border px-2 py-[2px] [font-family:var(--font-mono)] text-[0.6rem] uppercase tracking-[0.1em] ${className}`}
    >
      {children}
    </span>
  );
}

function CompactForecastViz({ forecast }: { forecast: ForecastListingItem }) {
  const lower = forecast.interval.lower.value;
  const upper = forecast.interval.upper.value;
  const span = upper - lower || 1;
  const pointPosition = Math.max(
    0,
    Math.min(100, ((forecast.point.value - lower) / span) * 100),
  );
  return (
    <div className="w-full">
      <div className="relative h-2 w-full rounded-full bg-[var(--theme-bg-surface)]">
        <div className="absolute left-[8%] h-2 w-[84%] rounded-full bg-[var(--color-horizon-300)] opacity-70" />
        <div
          className="absolute top-1/2 h-3 w-[2px] -translate-y-1/2 bg-[var(--color-accent)]"
          style={{ left: `${8 + pointPosition * 0.84}%` }}
        />
      </div>
      <div className="mt-1 flex justify-between [font-family:var(--font-mono)] text-[0.62rem] text-[var(--theme-text-dim)]">
        <span>{forecast.interval.lower.label}</span>
        <span className="font-medium text-[var(--color-accent)]">
          {forecast.point.label}
        </span>
        <span>{forecast.interval.upper.label}</span>
      </div>
    </div>
  );
}

function formatResolutionLabel(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    year: "numeric",
  });
}

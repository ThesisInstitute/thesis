import Link from "next/link";
import { BrierLogoMark } from "./BrierLogo";

type Page =
  | "docs"
  | "thesis"
  | "brier"
  | "paper"
  | "forecasts"
  | "bills"
  | "briefings"
  | "log"
  | "calibration"
  | "models";

const primaryLinks: { page: Page; href: string; label: string }[] = [
  { page: "forecasts", href: "/", label: "Forecasts" },
  { page: "bills", href: "/bills", label: "Bills" },
  { page: "paper", href: "/paper", label: "Research" },
];

const moreLinks: { page: Page; href: string; label: string }[] = [
  { page: "briefings", href: "/briefings", label: "Briefings" },
  { page: "models", href: "/models", label: "Models" },
  { page: "calibration", href: "/calibration", label: "Calibration" },
  { page: "log", href: "/log", label: "Log" },
  { page: "docs", href: "/docs", label: "Docs" },
  { page: "thesis", href: "/thesis", label: "Thesis" },
  { page: "brier", href: "/brier", label: "Brier" },
];

const linkClass =
  "inline-flex min-h-11 items-center no-underline hover:text-[var(--color-accent)] hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--color-accent)]";

export function Header({ activePage }: { activePage?: Page }) {
  const moreIsActive = moreLinks.some(({ page }) => page === activePage);

  return (
    <header
      className="sticky top-0 z-100 w-full border-b backdrop-blur-[16px]"
      style={{
        backgroundColor: "var(--theme-header-bg)",
        borderColor: "var(--theme-border)",
      }}
    >
      <div className="mx-auto flex w-full max-w-[1200px] items-center justify-between gap-x-8 px-8 py-2 max-sm:flex-wrap max-sm:px-5 max-sm:pt-3 max-sm:pb-1">
        <div className="flex min-w-0 items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-[0.35em] [font-family:var(--font-display)] text-[1.1rem] font-semibold tracking-[-0.01em] no-underline hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--color-accent)]"
            style={{ color: "var(--theme-text)" }}
          >
            <BrierLogoMark size={26} />
            <span>thesis</span>
          </Link>
          <span
            className="text-[0.72rem] text-[var(--theme-text-muted)]"
            aria-label="Prototype build"
          >
            Prototype
          </span>
        </div>

        <nav
          aria-label="Main navigation"
          className="flex items-center gap-7 [font-family:var(--font-body)] text-[0.85rem] text-[var(--theme-text-muted)] max-sm:w-full max-sm:justify-between max-sm:gap-3"
        >
          {primaryLinks.map(({ page, href, label }) => {
            const props = {
              href,
              className: `${linkClass} ${activePage === page ? "text-[var(--color-accent)]" : ""}`,
              "aria-current":
                activePage === page ? ("page" as const) : undefined,
            };
            // Research is served by Quarto, outside the Next app router.
            return page === "paper" ? (
              <a key={page} {...props}>
                {label}
              </a>
            ) : (
              <Link key={page} {...props}>
                {label}
              </Link>
            );
          })}

          <details className="group relative">
            <summary
              className={`${linkClass} cursor-pointer list-none gap-1.5 [&::-webkit-details-marker]:hidden ${moreIsActive ? "text-[var(--color-accent)]" : ""}`}
            >
              More
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                aria-hidden="true"
                className="group-open:rotate-180"
              >
                <path
                  d="m3 4.5 3 3 3-3"
                  stroke="currentColor"
                  strokeWidth="1.25"
                />
              </svg>
            </summary>
            <div className="absolute right-0 top-full mt-2 max-h-[70vh] w-48 overflow-y-auto border border-[var(--theme-border)] bg-[var(--theme-bg-elevated)] px-4 py-2 shadow-sm">
              {moreLinks.map(({ page, href, label }) => (
                <Link
                  key={page}
                  href={href}
                  aria-current={activePage === page ? "page" : undefined}
                  className={`${linkClass} w-full ${activePage === page ? "text-[var(--color-accent)]" : ""}`}
                >
                  {label}
                </Link>
              ))}
              <a
                href="https://github.com/ThesisInstitute/thesis"
                aria-label="GitHub"
                className={`${linkClass} w-full`}
              >
                GitHub ↗
              </a>
            </div>
          </details>
        </nav>
      </div>
    </header>
  );
}

import { getPublishedForecasts } from "@/lib/forecast-publication";
import Link from "next/link";
import { Header } from "@/components/Header";
import { loadBills } from "@/data/bills";
import { formatValue } from "@/data/forecast-cells";

const featuredForecasts = getPublishedForecasts()
  .filter((forecast) => forecast.type === "data")
  .slice(0, 3);

const stackItems = [
  {
    label: "Open forecasts",
    title: "Agents publish predictions before reality arrives.",
    body: "The public surface tracks government statistics, policy settings, and conditional outcomes with resolution rules and calibrated uncertainty.",
    href: "/forecasts",
  },
  {
    label: "PolicyEngine",
    title: "Policy simulations stay inspectable.",
    body: "Tax and benefit forecasts call open microsimulation models instead of treating model outputs as hidden oracle claims.",
    href: "https://policyengine.org",
  },
  {
    label: "Microplex",
    title: "Synthetic populations become forecasting substrate.",
    body: "Calibrated microdata lets agents test policy scenarios against transparent population structure and administrative benchmarks.",
    href: "/vision",
  },
  {
    label: "Brier Decisions",
    title: "Everyday agent advice becomes scoreable.",
    body: "The personal decision package keeps the same discipline for local choices: outcomes, uncertainty, review dates, and calibration.",
    href: "/docs",
  },
];

const methodSteps = [
  "Define the public outcome and the exact source that will resolve it.",
  "Call official data, encoded law, PolicyEngine, and other inspectable tools.",
  "Publish the forecast distribution, public trace, and later score.",
];

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-[#D9E4EC] bg-[#F7FAFC]">
      <div
        className="absolute inset-0 opacity-70"
        style={{
          background:
            "linear-gradient(115deg, rgba(247,250,252,0.96) 0%, rgba(247,250,252,0.86) 45%, rgba(238,244,248,0.72) 100%)",
        }}
      />
      <div className="relative mx-auto grid min-h-[calc(100svh-74px)] max-w-[1200px] grid-cols-[minmax(0,0.95fr)_minmax(360px,1fr)] items-center gap-14 px-8 py-16 max-lg:grid-cols-1 max-md:min-h-[auto] max-md:px-5 max-md:py-12">
        <div className="max-w-[650px] animate-[fade-up_0.7s_ease-out]">
          <p className="[font-family:var(--font-mono)] mb-5 text-[0.68rem] font-medium uppercase tracking-[0.16em] text-[#A94E80]">
            Thesis Institute
          </p>
          <h1 className="[font-family:var(--font-display)] mb-6 text-[clamp(2.7rem,7vw,5.8rem)] font-light leading-[0.95] tracking-[-0.03em] text-[#14202B]">
            Open-source forecasting agents for public outcomes.
          </h1>
          <p className="mb-8 max-w-[560px] text-[1.05rem] leading-[1.7] text-[#415463]">
            We build agents whose job is to predict consequential public facts,
            explain the evidence, call inspectable tools, and learn from scored
            outcomes.
          </p>
          <div className="flex flex-wrap gap-4">
            <Link
              href="/forecasts"
              className="inline-flex items-center rounded-lg bg-[#14202B] px-6 py-[0.78em] [font-family:var(--font-display)] text-[0.9rem] font-semibold text-white no-underline shadow-[0_2px_8px_rgba(20,32,43,0.12)] transition-all duration-200 hover:-translate-y-[1px] hover:no-underline"
            >
              Open forecasts
            </Link>
            <Link
              href="/vision"
              className="inline-flex items-center rounded-lg border border-[#BED0DB] bg-white px-6 py-[0.78em] [font-family:var(--font-display)] text-[0.9rem] font-medium text-[#415463] no-underline transition-all duration-200 hover:border-[#A94E80] hover:text-[#14202B] hover:no-underline"
            >
              Read the vision
            </Link>
          </div>
        </div>

        <div className="relative min-h-[520px] animate-[fade-up_0.7s_ease-out_0.14s_both] max-lg:min-h-[420px] max-md:min-h-[340px]">
          <div className="absolute inset-0">
            <div className="absolute left-[8%] top-[8%] h-[70%] w-px bg-[#BED0DB]" />
            <div className="absolute left-[28%] top-[18%] h-[68%] w-px bg-[#D9E4EC]" />
            <div className="absolute left-[54%] top-[4%] h-[82%] w-px bg-[#BED0DB]" />
            <div className="absolute left-[78%] top-[20%] h-[62%] w-px bg-[#D9E4EC]" />
            <div className="absolute left-[8%] top-[18%] h-px w-[72%] bg-[#D9E4EC]" />
            <div className="absolute left-[2%] top-[42%] h-px w-[86%] bg-[#BED0DB]" />
            <div className="absolute left-[18%] top-[70%] h-px w-[76%] bg-[#D9E4EC]" />
          </div>
          {featuredForecasts.map((forecast, index) => (
            <Link
              key={forecast.slug}
              href={`/forecasts/${forecast.slug}`}
              className={`absolute block w-[min(88%,420px)] rounded-[6px] border border-[#D9E4EC] bg-white/92 p-5 text-left no-underline shadow-[0_18px_45px_rgba(20,32,43,0.08)] backdrop-blur-sm transition-all duration-200 hover:-translate-y-1 hover:border-[#A94E80] hover:no-underline ${
                index === 0
                  ? "left-[2%] top-[9%]"
                  : index === 1
                    ? "right-[0%] top-[37%]"
                    : "left-[16%] bottom-[5%]"
              }`}
            >
              <p className="[font-family:var(--font-mono)] mb-3 text-[0.6rem] uppercase tracking-[0.14em] text-[#6B7C89]">
                {forecast.country} · {forecast.type}
              </p>
              <h2 className="[font-family:var(--font-display)] mb-3 text-[1.18rem] font-medium leading-[1.22] tracking-[-0.01em] text-[#14202B]">
                {forecast.title}
              </h2>
              <div className="flex items-end justify-between gap-4">
                <p className="[font-family:var(--font-mono)] text-[0.72rem] uppercase tracking-[0.08em] text-[#A94E80]">
                  {formatValue(forecast.pointEstimate, forecast.unit)}
                </p>
                <p className="text-right [font-family:var(--font-mono)] text-[0.64rem] uppercase tracking-[0.1em] text-[#6B7C89]">
                  resolves {forecast.resolutionDate}
                </p>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

function StackSection() {
  return (
    <section className="bg-white px-8 py-[clamp(84px,10vw,132px)] max-md:px-5">
      <div className="mx-auto max-w-[1120px]">
        <div className="mb-14 max-w-[720px]">
          <p className="[font-family:var(--font-mono)] mb-4 text-[0.68rem] font-medium uppercase tracking-[0.14em] text-[#A94E80]">
            The stack
          </p>
          <h2 className="[font-family:var(--font-display)] text-[clamp(2rem,4vw,3rem)] font-light leading-[1.08] tracking-[-0.025em] text-[#14202B]">
            We connect prediction, law, data, and simulation in one open loop.
          </h2>
        </div>
        <div className="divide-y divide-[#D9E4EC] border-y border-[#D9E4EC]">
          {stackItems.map((item) => (
            <Link
              key={item.label}
              href={item.href}
              className="grid grid-cols-[180px_minmax(0,1fr)_24px] gap-8 py-7 text-[#14202B] no-underline transition-colors duration-200 hover:text-[#A94E80] hover:no-underline max-md:grid-cols-1 max-md:gap-3"
            >
              <p className="[font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.14em] text-[#6B7C89]">
                {item.label}
              </p>
              <div>
                <h3 className="[font-family:var(--font-display)] mb-2 text-[1.35rem] font-medium leading-[1.18] tracking-[-0.01em]">
                  {item.title}
                </h3>
                <p className="max-w-[720px] text-[0.95rem] leading-[1.65] text-[#415463]">
                  {item.body}
                </p>
              </div>
              <span className="self-center text-[1.4rem] max-md:hidden">→</span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

function MethodSection() {
  return (
    <section className="bg-[#EEF4F8] px-8 py-[clamp(84px,10vw,132px)] max-md:px-5">
      <div className="mx-auto grid max-w-[1120px] grid-cols-[minmax(0,0.9fr)_minmax(320px,1fr)] gap-14 max-lg:grid-cols-1">
        <div>
          <p className="[font-family:var(--font-mono)] mb-4 text-[0.68rem] font-medium uppercase tracking-[0.14em] text-[#5E7A8D]">
            Forecasting as alignment pressure
          </p>
          <h2 className="[font-family:var(--font-display)] mb-5 text-[clamp(1.9rem,3.8vw,2.8rem)] font-light leading-[1.1] tracking-[-0.025em] text-[#14202B]">
            A system that must predict reality has to stay accountable to it.
          </h2>
          <p className="text-[1rem] leading-[1.7] text-[#415463]">
            Forecasting gives AI systems a narrow public job, a hard feedback
            loop, and a record others can inspect. The work compounds when each
            resolved outcome improves the next agent run.
          </p>
        </div>
        <ol className="divide-y divide-[#C9D8E2] border-y border-[#C9D8E2]">
          {methodSteps.map((step, index) => (
            <li key={step} className="flex gap-6 py-7">
              <span className="[font-family:var(--font-mono)] text-[0.72rem] text-[#A94E80]">
                0{index + 1}
              </span>
              <p className="m-0 text-[1.05rem] leading-[1.55] text-[#14202B]">
                {step}
              </p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function ForecastPreview() {
  return (
    <section className="bg-[#F7FAFC] px-8 py-[clamp(84px,10vw,132px)] max-md:px-5">
      <div className="mx-auto max-w-[1120px]">
        <div className="mb-12 flex items-end justify-between gap-8 max-md:block">
          <div className="max-w-[680px]">
            <p className="[font-family:var(--font-mono)] mb-4 text-[0.68rem] font-medium uppercase tracking-[0.14em] text-[#A94E80]">
              Public preview
            </p>
            <h2 className="[font-family:var(--font-display)] text-[clamp(1.9rem,3.8vw,2.8rem)] font-light leading-[1.1] tracking-[-0.025em] text-[#14202B]">
              The forecast app lives one level deeper.
            </h2>
          </div>
          <Link
            href="/forecasts"
            className="inline-flex items-center rounded-lg border border-[#BED0DB] bg-white px-5 py-[0.72em] [font-family:var(--font-display)] text-[0.88rem] font-medium text-[#415463] no-underline transition-colors duration-200 hover:border-[#A94E80] hover:text-[#14202B] hover:no-underline max-md:mt-6"
          >
            View all forecasts
          </Link>
        </div>
        <div className="divide-y divide-[#D9E4EC] border-y border-[#D9E4EC]">
          {featuredForecasts.map((forecast) => (
            <Link
              key={forecast.slug}
              href={`/forecasts/${forecast.slug}`}
              className="grid grid-cols-[minmax(0,1fr)_160px_160px] items-center gap-8 py-6 text-[#14202B] no-underline transition-colors duration-200 hover:text-[#A94E80] hover:no-underline max-md:grid-cols-1 max-md:gap-2"
            >
              <div>
                <p className="[font-family:var(--font-mono)] mb-2 text-[0.62rem] uppercase tracking-[0.12em] text-[#6B7C89]">
                  {forecast.country} · {forecast.type}
                </p>
                <h3 className="[font-family:var(--font-display)] text-[1.2rem] font-medium leading-[1.25]">
                  {forecast.title}
                </h3>
              </div>
              <p className="[font-family:var(--font-mono)] text-[0.8rem] text-[#415463]">
                {formatValue(forecast.pointEstimate, forecast.unit)}
              </p>
              <p className="text-right [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[#6B7C89] max-md:text-left">
                {forecast.resolutionDate}
              </p>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}

function BillsPreview() {
  const bills = loadBills();
  if (bills.length === 0) return null;
  return (
    <section className="bg-white px-8 py-[clamp(84px,10vw,132px)] max-md:px-5">
      <div className="mx-auto max-w-[1120px]">
        <div className="mb-12 flex items-end justify-between gap-8 max-md:block">
          <div className="max-w-[680px]">
            <p className="[font-family:var(--font-mono)] mb-4 text-[0.68rem] font-medium uppercase tracking-[0.14em] text-[#A94E80]">
              Bill analyses
            </p>
            <h2 className="[font-family:var(--font-display)] text-[clamp(1.9rem,3.8vw,2.8rem)] font-light leading-[1.1] tracking-[-0.025em] text-[#14202B]">
              Start from the bill, derive the outcomes.
            </h2>
          </div>
          <Link
            href="/bills"
            className="inline-flex items-center rounded-lg border border-[#BED0DB] bg-white px-5 py-[0.72em] [font-family:var(--font-display)] text-[0.88rem] font-medium text-[#415463] no-underline transition-colors duration-200 hover:border-[#A94E80] hover:text-[#14202B] hover:no-underline max-md:mt-6"
          >
            View all bills
          </Link>
        </div>
        <div className="divide-y divide-[#D9E4EC] border-y border-[#D9E4EC]">
          {bills.map((entry) => {
            const metricCount = entry.provisions.reduce(
              (sum, provision) => sum + provision.metrics.length,
              0,
            );
            return (
              <Link
                key={entry.slug}
                href={`/bills/${entry.slug}`}
                className="grid grid-cols-[minmax(0,1fr)_160px_160px] items-center gap-8 py-6 text-[#14202B] no-underline transition-colors duration-200 hover:text-[#A94E80] hover:no-underline max-md:grid-cols-1 max-md:gap-2"
              >
                <div>
                  <p className="[font-family:var(--font-mono)] mb-2 text-[0.62rem] uppercase tracking-[0.12em] text-[#6B7C89]">
                    {entry.bill.status}
                  </p>
                  <h3 className="[font-family:var(--font-display)] text-[1.2rem] font-medium leading-[1.25]">
                    {entry.bill.name}
                  </h3>
                </div>
                <p className="[font-family:var(--font-mono)] text-[0.8rem] text-[#415463]">
                  {entry.provisions.length} provisions · {metricCount} metrics
                </p>
                <p className="text-right [font-family:var(--font-mono)] text-[0.68rem] uppercase tracking-[0.1em] text-[#6B7C89] max-md:text-left">
                  {entry.bill.analysisDate}
                </p>
              </Link>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-[#D9E4EC] bg-white px-8 py-12 max-md:px-5">
      <div className="mx-auto flex max-w-[1120px] items-center justify-between gap-6 max-md:block">
        <p className="[font-family:var(--font-display)] text-[1.1rem] font-medium text-[#14202B]">
          Thesis Institute
        </p>
        <div className="flex gap-6 text-[0.78rem] [font-family:var(--font-mono)] max-md:mt-5 max-md:flex-wrap">
          <Link
            href="/forecasts"
            className="text-[#6B7C89] no-underline transition-colors hover:text-[#14202B]"
          >
            Forecasts
          </Link>
          <Link
            href="/bills"
            className="text-[#6B7C89] no-underline transition-colors hover:text-[#14202B]"
          >
            Bills
          </Link>
          <Link
            href="/vision"
            className="text-[#6B7C89] no-underline transition-colors hover:text-[#14202B]"
          >
            Vision
          </Link>
          <Link
            href="/docs"
            className="text-[#6B7C89] no-underline transition-colors hover:text-[#14202B]"
          >
            Brier Decisions
          </Link>
          <a
            href="https://policyengine.org"
            className="text-[#6B7C89] no-underline transition-colors hover:text-[#14202B]"
          >
            PolicyEngine
          </a>
        </div>
      </div>
    </footer>
  );
}

export default function HomePage() {
  return (
    <div className="min-h-screen bg-[#F7FAFC] text-[#14202B]">
      <Header />
      <Hero />
      <StackSection />
      <MethodSection />
      <ForecastPreview />
      <BillsPreview />
      <Footer />
    </div>
  );
}

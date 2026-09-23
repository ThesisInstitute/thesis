import Link from "next/link";
import { Header } from "@/components/Header";
import { DemoVideo } from "@/components/DemoVideo";

function CodeBlock({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="rounded-2xl p-5 overflow-x-auto"
      style={{
        background: "linear-gradient(180deg, #292524 0%, #1C1917 100%)",
        border: "1px solid #44403C",
      }}
    >
      <pre className="[font-family:var(--font-mono)] text-[0.78rem] leading-[1.75] text-[#FAFAF9] whitespace-pre-wrap m-0">
        {children}
      </pre>
    </div>
  );
}

function Section({
  kicker,
  title,
  children,
}: {
  kicker: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="py-16 border-b border-[#E7E5E4] last:border-b-0">
      <div className="mb-8">
        <div className="[font-family:var(--font-mono)] text-[0.68rem] tracking-[0.12em] uppercase text-[#A94E80] mb-3">
          {kicker}
        </div>
        <h2 className="[font-family:var(--font-display)] text-[clamp(1.6rem,3vw,2.3rem)] font-medium leading-[1.08] tracking-[-0.03em] text-[#1C1917]">
          {title}
        </h2>
      </div>
      {children}
    </section>
  );
}

export default function DocsPage() {
  return (
    <div className="bg-[#FAF9F6] text-[#1C1917] min-h-screen grain-overlay">
      <Header activePage="docs" />
      <main className="max-w-[1100px] mx-auto px-8 max-md:px-4 pb-24">
        <header className="py-20 max-md:py-14 border-b border-[#E7E5E4]">
          <div className="[font-family:var(--font-mono)] text-[0.72rem] tracking-[0.12em] uppercase text-[#A94E80] mb-5">
            Documentation
          </div>
          <h1 className="[font-family:var(--font-display)] text-[clamp(2.1rem,5vw,3.4rem)] font-medium leading-[1.02] tracking-[-0.04em] text-[#1C1917] max-w-[820px] mb-6">
            Use brier with Codex, Claude Code, or the local CLI.
          </h1>
          <p className="text-[1.02rem] text-[#57534E] leading-[1.7] max-w-[760px] mb-8">
            The install story is package-first. The PyPI package now includes
            the CLI, MCP server, and packaged Codex and Claude skills. The CLI
            itself is local-only and does not call an LLM or require an API key.
          </p>

          <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
            <div className="rounded-2xl bg-white border border-[#E7E5E4] p-5">
              <div className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.08em] text-[#A94E80] mb-2">
                Recommended
              </div>
              <div className="[font-family:var(--font-display)] text-[1.1rem] font-semibold text-[#1C1917] mb-2">
                Codex + MCP
              </div>
              <p className="text-[0.88rem] leading-[1.6] text-[#57534E] m-0">
                Best path if you want native tools, persistent decisions, and
                the `$brier` trigger.
              </p>
            </div>
            <div className="rounded-2xl bg-white border border-[#E7E5E4] p-5">
              <div className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.08em] text-[#57534E] mb-2">
                Local
              </div>
              <div className="[font-family:var(--font-display)] text-[1.1rem] font-semibold text-[#1C1917] mb-2">
                CLI / Python
              </div>
              <p className="text-[0.88rem] leading-[1.6] text-[#57534E] m-0">
                Use this if you want a decision log and calibration loop without
                any agent integration.
              </p>
            </div>
            <div className="rounded-2xl bg-white border border-[#E7E5E4] p-5">
              <div className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.08em] text-[#57534E] mb-2">
                Plugin
              </div>
              <div className="[font-family:var(--font-display)] text-[1.1rem] font-semibold text-[#1C1917] mb-2">
                Claude Code
              </div>
              <p className="text-[0.88rem] leading-[1.6] text-[#57534E] m-0">
                Use the plugin if you want the slash-command flow and
                Claude-specific integration.
              </p>
            </div>
          </div>
        </header>

        <Section kicker="Install" title="Install the package and choose a path">
          <div
            id="install"
            className="grid grid-cols-3 gap-6 max-md:grid-cols-1"
          >
            <div className="space-y-4">
              <h3 className="[font-family:var(--font-display)] text-[1.2rem] font-semibold text-[#1C1917]">
                1. Codex with MCP
              </h3>
              <p className="text-[0.92rem] text-[#57534E] leading-[1.65]">
                This gives Codex native tools, access to stored decisions, and a
                reusable `$brier` skill.
              </p>
              <CodeBlock>{`python -m pip install 'brier[mcp]'
brier setup codex
# restart Codex, then use $brier`}</CodeBlock>
            </div>

            <div className="space-y-4">
              <h3 className="[font-family:var(--font-display)] text-[1.2rem] font-semibold text-[#1C1917]">
                2. Claude Code local skill
              </h3>
              <p className="text-[0.92rem] text-[#57534E] leading-[1.65]">
                This gives Claude Code the same local MCP-backed workflow as
                Codex, but through Claude skills instead of the Codex skill
                format.
              </p>
              <CodeBlock>{`python -m pip install 'brier[mcp]'
brier setup claude
# restart Claude Code`}</CodeBlock>
            </div>

            <div className="space-y-4">
              <h3 className="[font-family:var(--font-display)] text-[1.2rem] font-semibold text-[#1C1917]">
                3. Local CLI / Python
              </h3>
              <p className="text-[0.92rem] text-[#57534E] leading-[1.65]">
                This path creates and scores decisions locally. No LLM API key
                is required for these commands.
              </p>
              <CodeBlock>{`python -m pip install brier
brier new "Should we rewrite the auth layer?"
brier list
brier calibration`}</CodeBlock>
            </div>
          </div>

          <div className="mt-8 rounded-2xl bg-white border border-[#E7E5E4] p-6">
            <div className="[font-family:var(--font-mono)] text-[0.7rem] uppercase tracking-[0.08em] text-[#57534E] mb-2">
              Optional
            </div>
            <div className="[font-family:var(--font-display)] text-[1.05rem] font-semibold text-[#1C1917] mb-2">
              Claude plugin path
            </div>
            <p className="text-[0.9rem] text-[#57534E] leading-[1.65] mb-4">
              If you prefer the older plugin flow instead of local Claude
              skills, it still works:
            </p>
            <CodeBlock>{`claude plugin marketplace add ThesisInstitute/thesis
claude plugin install brier@maxghenis-plugins
# then use /brier:decide`}</CodeBlock>
          </div>
        </Section>

        <Section kicker="Architecture" title="What each piece actually does">
          <div className="grid grid-cols-2 gap-4 max-md:grid-cols-1">
            {[
              [
                "CLI",
                "Creates, lists, reviews, and scores decisions in ~/.brier/decisions.jsonl.",
              ],
              [
                "MCP server",
                "Exposes the same decision store as native tools, resources, and prompts for agent clients.",
              ],
              [
                "Codex skill",
                "Tells Codex when to use the MCP tools and what the brier workflow should produce.",
              ],
              [
                "Claude skill",
                "Tells Claude Code when to use the same local MCP server. The older plugin path stays optional.",
              ],
            ].map(([title, description]) => (
              <div
                key={title}
                className="rounded-2xl bg-white border border-[#E7E5E4] p-6"
              >
                <div className="[font-family:var(--font-mono)] text-[0.72rem] tracking-[0.04em] text-[#A94E80] mb-3">
                  {title}
                </div>
                <p className="text-[0.9rem] text-[#57534E] leading-[1.6] m-0">
                  {description}
                </p>
              </div>
            ))}
          </div>
        </Section>

        <Section
          kicker="Quickstart"
          title="Two commands, then restart the client"
        >
          <div className="grid grid-cols-2 gap-6 max-md:grid-cols-1">
            <CodeBlock>{`python -m pip install 'brier[mcp]'
brier setup codex`}</CodeBlock>
            <CodeBlock>{`python -m pip install 'brier[mcp]'
brier setup claude`}</CodeBlock>
          </div>
          <p className="mt-5 text-[0.92rem] text-[#57534E] leading-[1.7] max-w-[760px]">
            `brier setup` installs the packaged skill and registers the local
            MCP server with the same Python interpreter that launched `brier`.
            The last step is just restarting Codex or Claude Code.
          </p>
          <div className="mt-6 grid grid-cols-2 gap-6 max-md:grid-cols-1">
            <CodeBlock>{`brier doctor codex`}</CodeBlock>
            <CodeBlock>{`brier doctor claude`}</CodeBlock>
          </div>
          <p className="mt-5 text-[0.92rem] text-[#57534E] leading-[1.7] max-w-[760px]">
            `brier doctor` checks three things: whether the packaged skill is
            installed, whether the agent CLI is on `PATH`, and whether the local
            MCP server is already registered.
          </p>
        </Section>

        <Section
          kicker="Walkthrough"
          title="See the packaged flow before you install"
        >
          <div className="grid grid-cols-[320px_minmax(0,1fr)] gap-8 items-start max-md:grid-cols-1">
            <div>
              <p className="text-[0.94rem] text-[#57534E] leading-[1.7] mb-5">
                This is the actual package-first Codex path from the docs:
                install, run setup, use
                <span className="[font-family:var(--font-mono)]">
                  {" "}
                  $brier{" "}
                </span>
                in Codex, then confirm the decision landed in the local store.
              </p>
              <CodeBlock>{`python -m pip install 'brier[mcp]'
brier setup codex
brier doctor codex`}</CodeBlock>
            </div>
            <DemoVideo caption="Rendered from a real Codex session using the local brier skill and MCP server, then exported as a clean 4K terminal demo." />
          </div>
        </Section>

        <Section kicker="Repair" title="Fix drifted installs or reset cleanly">
          <div className="grid grid-cols-2 gap-6 max-md:grid-cols-1">
            <div className="space-y-4">
              <h3 className="[font-family:var(--font-display)] text-[1.2rem] font-semibold text-[#1C1917]">
                Repair in place
              </h3>
              <p className="text-[0.92rem] text-[#57534E] leading-[1.65]">
                If the skill file drifted, the agent CLI moved, or MCP setup
                only half-worked, let `doctor` repair what it can.
              </p>
              <CodeBlock>{`brier doctor codex --fix
brier doctor claude --fix`}</CodeBlock>
            </div>
            <div className="space-y-4">
              <h3 className="[font-family:var(--font-display)] text-[1.2rem] font-semibold text-[#1C1917]">
                Reset from scratch
              </h3>
              <p className="text-[0.92rem] text-[#57534E] leading-[1.65]">
                Remove the local skill and MCP registration, then run setup
                again.
              </p>
              <CodeBlock>{`brier uninstall codex
brier setup codex

brier uninstall claude
brier setup claude`}</CodeBlock>
            </div>
          </div>
        </Section>

        <Section kicker="Workflow" title="What to expect from the framework">
          <div className="grid grid-cols-2 gap-8 max-md:grid-cols-1">
            <div className="space-y-4">
              <p className="text-[0.94rem] text-[#57534E] leading-[1.7]">
                The framework is not “ask an LLM for advice.” It is a structured
                decision workflow:
              </p>
              <ol className="list-decimal pl-5 text-[0.92rem] text-[#57534E] leading-[1.8]">
                <li>Define the KPI and time horizon.</li>
                <li>Expand the option set beyond the initial framing.</li>
                <li>Anchor on a reference class or base rate.</li>
                <li>Show the mechanism or decomposition.</li>
                <li>Surface disconfirming evidence and traps.</li>
                <li>Give point estimates with 80% confidence intervals.</li>
                <li>Set a review date and score outcomes later.</li>
              </ol>
            </div>
            <CodeBlock>{`Decision: Should we rewrite the auth layer now?
KPI: critical_auth_incidents / 90d
Options: rewrite now | defer 60d | harden existing system
Base rate: 27% of similar infra rewrites produce >40% reliability gains
Forecast (rewrite now): 58% [42, 71]
Disconfirming evidence: ops fixes may solve this faster
Review date: 2026-06-15`}</CodeBlock>
          </div>
        </Section>

        <Section kicker="Forecasts" title="Draft public forecast questions">
          <div className="grid grid-cols-2 gap-8 max-md:grid-cols-1">
            <div className="space-y-4">
              <p className="text-[0.94rem] text-[#57534E] leading-[1.7]">
                `brier forecast-draft` turns a stored decision forecast or a
                standalone policy question into Manifold-ready JSON. It is
                intentionally draft-only: it does not publish anything, place a
                bet, or require a Manifold API key.
              </p>
              <p className="text-[0.94rem] text-[#57534E] leading-[1.7]">
                For public policy questions, use it to turn a live debate into a
                falsifiable forecast with explicit resolution criteria before
                anyone posts a public question. The Waymo/DC example uses an
                existing Manifold public-service question as the gate, then
                drafts conditional aggregate 2027 safety forecasts for DC
                traffic fatalities and serious injuries.
              </p>
            </div>
            <CodeBlock>{`brier forecast-draft \\
  "Will Waymo be legally permitted to offer fully driverless paid robotaxi rides in Washington, DC by 2026-12-31?" \\
  --initial-prob 52 \\
  --resolution-date 2026-12-31 \\
  --visibility unlisted \\
  --output waymo-dc-forecast-pack.json

# From a stored decision with forecasts:
brier forecast-draft abc123 --output forecast-pack.json`}</CodeBlock>
          </div>
        </Section>

        <Section kicker="Examples" title="Three concrete ways to use it">
          <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
            {[
              {
                title: "Architecture",
                body: "Should we rewrite the auth layer now or harden the existing service first?",
                code: `KPI: critical_auth_incidents / 90d
Options: rewrite now | defer 60d | harden existing
Forecast: rewrite now 58% [42, 71]
Base rate: 27%`,
              },
              {
                title: "Product",
                body: "Should we launch the new onboarding flow this sprint or hold for one more iteration?",
                code: `KPI: activated_users / signup cohort
Options: ship now | hold 2 weeks | A/B limited rollout
Forecast: limited rollout 64% [49, 77]
Disconfirming evidence: sample size may be too small`,
              },
              {
                title: "Hiring",
                body: "Should we hire a generalist engineer now or wait for a more specialized infra candidate?",
                code: `KPI: roadmap throughput / quarter
Options: hire generalist | wait for specialist | contractor bridge
Forecast: contractor bridge 51% [38, 63]
Review date: 2026-09-01`,
              },
            ].map((example) => (
              <div
                key={example.title}
                className="rounded-2xl bg-white border border-[#E7E5E4] p-6"
              >
                <div className="[font-family:var(--font-display)] text-[1rem] font-semibold text-[#1C1917] mb-2">
                  {example.title}
                </div>
                <p className="text-[0.9rem] leading-[1.6] text-[#57534E] mb-4">
                  {example.body}
                </p>
                <CodeBlock>{example.code}</CodeBlock>
              </div>
            ))}
          </div>
        </Section>

        <Section kicker="API keys" title="What needs credentials">
          <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
            <div className="rounded-2xl bg-white border border-[#E7E5E4] p-6">
              <div className="[font-family:var(--font-display)] text-[1rem] font-semibold text-[#1C1917] mb-2">
                CLI
              </div>
              <p className="text-[0.9rem] leading-[1.6] text-[#57534E] m-0">
                No model credentials required. The CLI reads and writes local
                decision records only.
              </p>
            </div>
            <div className="rounded-2xl bg-white border border-[#E7E5E4] p-6">
              <div className="[font-family:var(--font-display)] text-[1rem] font-semibold text-[#1C1917] mb-2">
                MCP + skills
              </div>
              <p className="text-[0.9rem] leading-[1.6] text-[#57534E] m-0">
                No separate brier API key. Your agent client uses its own
                normal model credentials.
              </p>
            </div>
            <div className="rounded-2xl bg-white border border-[#E7E5E4] p-6">
              <div className="[font-family:var(--font-display)] text-[1rem] font-semibold text-[#1C1917] mb-2">
                Experiments
              </div>
              <p className="text-[0.9rem] leading-[1.6] text-[#57534E] m-0">
                The experiment runners do call external models and need provider
                keys like `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
              </p>
            </div>
          </div>
        </Section>

        <Section kicker="Troubleshooting" title="The common failure cases">
          <div className="grid grid-cols-3 gap-4 max-md:grid-cols-1">
            {[
              {
                title: "Skill installed, not triggering",
                body: "Run `brier doctor codex` or `brier doctor claude`, then restart the client. Skills are loaded at startup.",
              },
              {
                title: "Agent CLI not found",
                body: "Install the `codex` or `claude` CLI first, then rerun `brier doctor --fix` to register MCP with the right interpreter.",
              },
              {
                title: "Want a clean reset",
                body: "Use `brier uninstall codex` or `brier uninstall claude`, then rerun `brier setup ...` instead of editing config by hand.",
              },
            ].map((item) => (
              <div
                key={item.title}
                className="rounded-2xl bg-white border border-[#E7E5E4] p-6"
              >
                <div className="[font-family:var(--font-display)] text-[1rem] font-semibold text-[#1C1917] mb-2">
                  {item.title}
                </div>
                <p className="text-[0.9rem] leading-[1.6] text-[#57534E] m-0">
                  {item.body}
                </p>
              </div>
            ))}
          </div>
        </Section>

        <Section kicker="References" title="Where to go next">
          <div className="flex gap-4 flex-wrap">
            <Link
              href="/paper"
              className="inline-flex items-center gap-2 py-[0.75em] px-5 [font-family:var(--font-display)] text-[0.88rem] font-medium no-underline rounded-lg bg-[#1C1917] text-[#FDFCFA]"
            >
              Read the paper
            </Link>
            <a
              href="https://github.com/ThesisInstitute/thesis/blob/main/docs/agent-workflows.md"
              className="inline-flex items-center gap-2 py-[0.75em] px-5 [font-family:var(--font-display)] text-[0.88rem] font-medium no-underline rounded-lg bg-white text-[#57534E] border border-[#D6D3D1]"
            >
              Agent workflow markdown
            </a>
            <a
              href="https://github.com/ThesisInstitute/thesis"
              className="inline-flex items-center gap-2 py-[0.75em] px-5 [font-family:var(--font-display)] text-[0.88rem] font-medium no-underline rounded-lg bg-white text-[#57534E] border border-[#D6D3D1]"
            >
              Repository
            </a>
          </div>
        </Section>
      </main>
    </div>
  );
}

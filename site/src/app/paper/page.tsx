import type { Metadata } from "next";
import { Header } from "@/components/Header";
import fs from "fs";
import Script from "next/script";
import path from "path";

function getQuartoContent(): { mainHtml: string; styles: string } {
  const htmlPath = path.join(process.cwd(), "public", "paper-raw", "index.html");

  try {
    const html = fs.readFileSync(htmlPath, "utf8");

    // Extract <main>...</main> content
    const mainStart = html.indexOf('<main class="content"');
    const mainEnd = html.indexOf("</main>") + "</main>".length;
    const mainHtml =
      mainStart >= 0 && mainEnd > mainStart
        ? html.substring(mainStart, mainEnd)
        : "<main><p>Paper content not found. Run quarto render first.</p></main>";

    // Extract inline <style> blocks
    const styleBlocks = html.match(/<style[^>]*>[\s\S]*?<\/style>/g) || [];

    // Build CSS link tags prefixed with /paper/, wrapped to scope
    const cssMatches =
      html.match(/<link href="[^"]*" rel="stylesheet"[^>]*>/g) || [];
    const cssLinks = cssMatches.map((link) =>
      link.replace(/href="([^"]*)"/, 'href="/paper-raw/$1"'),
    );

    const styles = [...cssLinks, ...styleBlocks].join("\n");

    // Rewrite image src paths: figures/... → /paper-raw/figures/...
    const fixedMainHtml = mainHtml.replace(
      /src="figures\//g,
      'src="/paper-raw/figures/',
    );

    return { mainHtml: fixedMainHtml, styles };
  } catch {
    return {
      mainHtml:
        "<main><p>Paper not yet rendered. Run: python3 paper/render_paper.py</p></main>",
      styles: "",
    };
  }
}

export const metadata: Metadata = {
  title: "Stability-under-probing — Axiom Forecasts",
};

export default function PaperPage() {
  const { mainHtml, styles } = getQuartoContent();

  // Wrap Quarto content in a container that isolates its CSS from the header
  const scopedHtml = `
    <div id="quarto-paper-scope">
      <style>
        /* Scope Quarto bootstrap to only affect paper content */
        #quarto-paper-scope {
          all: initial;
          display: block;
          font-family: "IBM Plex Sans", -apple-system, sans-serif;
          color: #1C1917;
          line-height: 1.7;
          max-width: 960px;
          margin: 0 auto;
          padding: 2rem;
        }
        #quarto-paper-scope * {
          box-sizing: border-box;
        }
        /* Override Quarto's global resets within scope */
        #quarto-paper-scope h1, #quarto-paper-scope h2, #quarto-paper-scope h3 {
          font-family: "Newsreader", Georgia, serif;
          color: #1C1917;
          margin-top: 2.5rem;
          margin-bottom: 1rem;
        }
        #quarto-paper-scope h1 { font-size: 2rem; font-weight: 600; letter-spacing: -0.02em; line-height: 1.25; margin-top: 0; }
        #quarto-paper-scope h2 { font-size: 1.4rem; font-weight: 500; }
        #quarto-paper-scope h3 { font-size: 1.1rem; font-weight: 500; }
        #quarto-paper-scope p { margin-bottom: 1rem; }
        #quarto-paper-scope a { color: #33547D; text-decoration: none; }
        #quarto-paper-scope a:hover { color: #A94E80; text-decoration: underline; }
        #quarto-paper-scope em { font-style: italic; }
        #quarto-paper-scope strong { font-weight: 600; }
        #quarto-paper-scope table { width: 100%; border-collapse: collapse; margin: 1.5rem 0; font-size: 0.9rem; }
        #quarto-paper-scope th { text-align: left; padding: 0.75rem; border-bottom: 2px solid #E7E5E4; font-weight: 600; }
        #quarto-paper-scope td { padding: 0.75rem; border-bottom: 1px solid #E7E5E4; }
        #quarto-paper-scope code { font-family: "IBM Plex Mono", monospace; background: #F5F5F4; padding: 0.15em 0.4em; border-radius: 3px; font-size: 0.88em; }
        #quarto-paper-scope pre { background: linear-gradient(180deg, #292524, #1C1917); color: #FAFAF9; padding: 1.5rem; border-radius: 12px; overflow-x: auto; margin: 1.5rem 0; border: 1px solid #44403C; }
        #quarto-paper-scope pre code { background: none; padding: 0; color: inherit; }
        #quarto-paper-scope blockquote { border-left: 3px solid #A94E80; padding: 1rem 1.5rem; margin: 1.5rem 0; background: #F6E7F0; border-radius: 0 8px 8px 0; }
        #quarto-paper-scope .quarto-appendix-contents { margin-top: 2rem; }
        #quarto-paper-scope #refs { font-size: 0.88rem; line-height: 1.6; }
        #quarto-paper-scope #refs p { margin-bottom: 0.5rem; }
        #quarto-paper-scope .csl-entry { margin-bottom: 0.75rem; }
        #quarto-paper-scope section { margin-bottom: 2rem; }
        #quarto-paper-scope img { max-width: 100%; height: auto; margin: 1rem 0; border-radius: 8px; }
        #quarto-paper-scope .math { font-style: normal; }
        #quarto-paper-scope #quarto-appendix { border-top: 1px solid #E7E5E4; padding-top: 2rem; margin-top: 3rem; }
      </style>
      ${mainHtml}
    </div>
  `;

  return (
    <div className="bg-[#FAF9F6] text-[#1C1917] min-h-screen">
      <Script id="paper-mathjax-config" strategy="beforeInteractive">
        {`
          window.MathJax = window.MathJax || {
            tex: {
              inlineMath: [['\\\\(', '\\\\)']],
              displayMath: [['\\\\[', '\\\\]']],
            },
          };
        `}
      </Script>
      <Script
        src="https://cdnjs.cloudflare.com/polyfill/v3/polyfill.min.js?features=es6"
        strategy="afterInteractive"
      />
      <Script
        src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml-full.js"
        strategy="afterInteractive"
      />
      <Script id="paper-mathjax-typeset" strategy="afterInteractive">
        {`
          (() => {
            const tryTypeset = () => {
              const root = document.getElementById("quarto-paper-scope");
              if (!root || !window.MathJax) {
                return false;
              }

              if (typeof window.MathJax.typesetClear === "function") {
                window.MathJax.typesetClear([root]);
              }

              if (typeof window.MathJax.typesetPromise === "function") {
                window.MathJax.typesetPromise([root]).catch(() => {});
                return true;
              }

              if (typeof window.MathJax.typeset === "function") {
                window.MathJax.typeset([root]);
                return true;
              }

              return false;
            };

            let attempts = 0;
            const poll = () => {
              if (tryTypeset() || attempts >= 20) {
                return;
              }
              attempts += 1;
              window.setTimeout(poll, 250);
            };

            poll();
            window.addEventListener("pageshow", poll);
          })();
        `}
      </Script>
      <Header activePage="paper" />
      <div className="animate-[fade-up_0.6s_ease-out]" dangerouslySetInnerHTML={{ __html: scopedHtml }} />
    </div>
  );
}

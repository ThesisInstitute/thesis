import type { ReasoningStep } from "@/data/forecast-cells";

// Recognize only the known billing/configuration messages. A generic match
// from "AI Gateway call failed:" to the paragraph's end could discard
// substantive methodology that follows an unfamiliar error.
const GATEWAY_DIAGNOSTIC =
  /AI Gateway call failed: Free tier users do not have access to this model\.(?: Upgrade to paid credits at https:\/\/vercel\.com\/\S+ for unrestricted access\.)?|AI Gateway credentials are not configured\./g;

export interface ReportContent {
  steps: ReasoningStep[];
  diagnostics: string[];
  modelUnavailable: boolean;
}

/** Prepare narrative for display while retaining the original diagnostic text. */
export function prepareReportContent(steps: ReasoningStep[]): ReportContent {
  const diagnostics = new Set<string>();
  const reportSteps: ReasoningStep[] = [];

  for (const step of steps) {
    // Recorded tool calls/results, formulas, and other steps are evidence:
    // display them exactly as supplied, including any errors they contain.
    if (step.kind !== "text") {
      reportSteps.push(step);
      continue;
    }

    let hasDiagnostic = false;
    const remainingText = step.text.replace(GATEWAY_DIAGNOSTIC, () => {
      hasDiagnostic = true;
      return "";
    });
    if (!hasDiagnostic) {
      reportSteps.push(step);
      continue;
    }

    diagnostics.add(step.text);
    if (!remainingText.trim()) continue;

    const text = step.text.replace(
      GATEWAY_DIAGNOSTIC,
      (_message, offset: number) => {
        const before = step.text.slice(0, offset);
        const startsSentence = !before.trim() || /[.!?]\s+$/.test(before);
        return startsSentence
          ? "The model request failed."
          : "the model request failed.";
      },
    );
    reportSteps.push({ ...step, text });
  }

  return {
    steps: reportSteps,
    diagnostics: [...diagnostics],
    modelUnavailable: diagnostics.size > 0,
  };
}

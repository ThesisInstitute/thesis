import { generateObject } from "ai";
import { z } from "zod";
import type { CpiDataset } from "@/lib/bls";
import type { SpmChildPovertyDataset } from "@/lib/census";
import type { CtcExpansionDataset } from "@/lib/policyengine";
import {
  AgentNumericCdfDistributionSchema,
  normalizeNumericCdfDistribution,
  summarizeNumericCdfDistribution,
  type NumericCdfDistribution,
} from "@/lib/prediction-distribution";

const ForecastSchema = z.object({
  distribution: AgentNumericCdfDistributionSchema,
  publicTrace: z.array(z.string().min(20).max(700)).min(3).max(6),
  assumptions: z.array(z.string().min(8).max(240)).min(2).max(6),
  dataCaveats: z.array(z.string().min(8).max(240)).min(1).max(4),
  drivers: z.array(z.string().min(4).max(80)).min(2).max(5),
});

const CtcExpansionForecastSchema = z.object({
  distribution: AgentNumericCdfDistributionSchema,
  publicTrace: z.array(z.string().min(20).max(700)).min(3).max(7),
  assumptions: z.array(z.string().min(8).max(240)).min(2).max(6),
  dataCaveats: z.array(z.string().min(8).max(240)).min(1).max(5),
  drivers: z.array(z.string().min(4).max(90)).min(2).max(5),
});

const SpmChildPovertyForecastSchema = z.object({
  distribution: AgentNumericCdfDistributionSchema,
  publicTrace: z.array(z.string().min(20).max(700)).min(3).max(7),
  assumptions: z.array(z.string().min(8).max(240)).min(2).max(6),
  dataCaveats: z.array(z.string().min(8).max(260)).min(1).max(5),
  drivers: z.array(z.string().min(4).max(90)).min(2).max(5),
});

export interface CpiForecast {
  pointEstimate: number;
  ciLow: number;
  ciHigh: number;
  confidence: 0.8;
  distribution: NumericCdfDistribution;
  publicTrace: string[];
  assumptions: string[];
  dataCaveats: string[];
  drivers: string[];
  source: "ai_gateway";
  model?: string;
  generatedAt: string;
}

export interface CtcExpansionForecast {
  pointEstimate: number;
  ciLow: number;
  ciHigh: number;
  confidence: 0.8;
  distribution: NumericCdfDistribution;
  publicTrace: string[];
  assumptions: string[];
  dataCaveats: string[];
  drivers: string[];
  source: "ai_gateway";
  model?: string;
  generatedAt: string;
}

export interface SpmChildPovertyForecast {
  pointEstimate: number;
  ciLow: number;
  ciHigh: number;
  confidence: 0.8;
  distribution: NumericCdfDistribution;
  publicTrace: string[];
  assumptions: string[];
  dataCaveats: string[];
  drivers: string[];
  source: "ai_gateway";
  model?: string;
  generatedAt: string;
}

export async function generateCpiForecast(
  dataset: CpiDataset,
): Promise<CpiForecast> {
  requireGateway();

  const model =
    process.env.THESIS_AI_MODEL ??
    process.env.BRIER_AI_MODEL ??
    "anthropic/claude-sonnet-4.6";

  try {
    const result = await generateObject({
      model,
      schema: ForecastSchema,
      temperature: 0.2,
      system:
        "You are a Thesis Institute public forecasting agent. Produce concise, audit-ready reasoning for public readers. Your public trace must name an explicit base rate or reference class (the distribution of recent comparable prints), state the mechanism behind the point estimate, and include at least one disconfirming consideration that would land the outcome outside your interval. Do not reveal hidden chain-of-thought; provide a public trace with evidence, assumptions, and uncertainty.",
      prompt: [
        "Forecast this public prediction cell:",
        "What will the annual average percent change in CPI-U for calendar year 2026 versus the 2025 annual average be, as published by BLS?",
        "",
        "Use the live BLS CPI-U data summary below. Return the predictive distribution as numeric_cdf_v1: exactly 201 evenly spaced CDF points over an explicit support, probability 0 at the first point, probability 1 at the last point, and monotone nondecreasing probabilities. Do not return pointEstimate, ciLow, or ciHigh as top-level fields; the server derives the median and 80% interval from the CDF. Keep the public trace factual, calibrated, and specific about data caveats.",
        "",
        JSON.stringify(dataset.summary, null, 2),
      ].join("\n"),
    });

    return normalizeForecast({
      ...ForecastSchema.parse(result.object),
      confidence: 0.8,
      source: "ai_gateway",
      model,
      generatedAt: new Date().toISOString(),
    });
  } catch (error) {
    throw new Error(
      error instanceof Error
        ? `AI forecast failed: ${error.message}`
        : "AI forecast failed.",
      { cause: error },
    );
  }
}

export async function generateCtcExpansionForecast(
  dataset: CtcExpansionDataset,
): Promise<CtcExpansionForecast> {
  requireGateway();

  const model =
    process.env.THESIS_AI_MODEL ??
    process.env.BRIER_AI_MODEL ??
    "anthropic/claude-sonnet-4.6";

  try {
    const result = await generateObject({
      model,
      schema: CtcExpansionForecastSchema,
      temperature: 0.2,
      system:
        "You are a Thesis Institute public forecasting agent. Forecast in billions of nominal dollars. Use public, audit-ready reasoning only. Your public trace must name an explicit base rate or reference class (the distribution of recent comparable prints), state the mechanism behind the point estimate, and include at least one disconfirming consideration that would land the outcome outside your interval. Treat PolicyEngine as an explicit model input, not as ground truth, and describe calibration adjustments without hidden chain-of-thought.",
      prompt: [
        "Forecast this public prediction cell:",
        dataset.summary.question,
        "",
        "Use the live PolicyEngine API result and the calibration prior below. Return the predictive distribution in billions of nominal dollars as numeric_cdf_v1: exactly 201 evenly spaced CDF points over an explicit support, probability 0 at the first point, probability 1 at the last point, and monotone nondecreasing probabilities. Do not return pointEstimate, ciLow, or ciHigh as top-level fields; the server derives the median and 80% interval from the CDF.",
        "If the PolicyEngine economy endpoint is still queued, errored, or timed out, explicitly disclose that the live model result is missing and identify any stored prior you use. Do not describe a stored prior as a fresh simulation.",
        "",
        JSON.stringify(
          {
            policyEngine: dataset.summary,
            economyStatus: dataset.economy,
          },
          null,
          2,
        ),
      ].join("\n"),
    });

    return normalizeUsdBillionsForecast({
      ...CtcExpansionForecastSchema.parse(result.object),
      confidence: 0.8,
      source: "ai_gateway",
      model,
      generatedAt: new Date().toISOString(),
    });
  } catch (error) {
    throw new Error(
      error instanceof Error
        ? `AI forecast failed: ${error.message}`
        : "AI forecast failed.",
      { cause: error },
    );
  }
}

export async function generateSpmChildPovertyForecast(
  dataset: SpmChildPovertyDataset,
): Promise<SpmChildPovertyForecast> {
  requireGateway();

  const model =
    process.env.THESIS_AI_MODEL ??
    process.env.BRIER_AI_MODEL ??
    "anthropic/claude-sonnet-4.6";

  try {
    const result = await generateObject({
      model,
      schema: SpmChildPovertyForecastSchema,
      temperature: 0.2,
      system:
        "You are a Thesis Institute public forecasting agent. Forecast in percentage points. Use public, audit-ready reasoning only. Your public trace must name an explicit base rate or reference class (the distribution of recent comparable prints), state the mechanism behind the point estimate, and include at least one disconfirming consideration that would land the outcome outside your interval. Treat Census history and PolicyEngine current-law inputs as explicit model inputs, not as ground truth, and describe calibration adjustments without hidden chain-of-thought.",
      prompt: [
        "Forecast this public prediction cell:",
        dataset.summary.question,
        "",
        "Target: the Census-published Supplemental Poverty Measure child poverty rate for calendar-year 2025, expected in the September 2026 income and poverty release.",
        "Use the live Census page evidence, historical SPM child-poverty series, PolicyEngine current-law policy check, and calibration prior below. Return the predictive distribution in percentage points as numeric_cdf_v1: exactly 201 evenly spaced CDF points over an explicit support, probability 0 at the first point, probability 1 at the last point, and monotone nondecreasing probabilities. Do not return pointEstimate, ciLow, or ciHigh as top-level fields; the server derives the median and 80% interval from the CDF.",
        "If the PolicyEngine check or Census page fetch is unavailable, explicitly widen or qualify uncertainty instead of pretending the data path is complete.",
        "",
        JSON.stringify(dataset.summary, null, 2),
      ].join("\n"),
    });

    return normalizeSpmPercentForecast({
      ...SpmChildPovertyForecastSchema.parse(result.object),
      confidence: 0.8,
      source: "ai_gateway",
      model,
      generatedAt: new Date().toISOString(),
    });
  } catch (error) {
    throw new Error(
      error instanceof Error
        ? `AI forecast failed: ${error.message}`
        : "AI forecast failed.",
      { cause: error },
    );
  }
}

function normalizeSpmPercentForecast(
  forecast: Omit<
    SpmChildPovertyForecast,
    "confidence" | "pointEstimate" | "ciLow" | "ciHigh"
  > & {
    confidence: 0.8;
  },
) {
  const distribution = normalizeNumericCdfDistribution({
    distribution: forecast.distribution,
    min: 0,
    max: 35,
    decimals: 1,
  });
  const summary = summarizeNumericCdfDistribution(distribution);

  return {
    ...forecast,
    ...summary,
    distribution,
    confidence: 0.8 as const,
  };
}

function requireGateway() {
  if (process.env.BRIER_DISABLE_AI === "1") {
    throw new Error("AI forecasting is disabled. No forecast was generated.");
  }
  if (
    !process.env.AI_GATEWAY_API_KEY &&
    !process.env.VERCEL_OIDC_TOKEN &&
    process.env.VERCEL !== "1"
  ) {
    throw new Error(
      "AI Gateway credentials are not configured. No forecast was generated.",
    );
  }
}

function normalizeForecast(
  forecast: Omit<
    CpiForecast,
    "confidence" | "pointEstimate" | "ciLow" | "ciHigh"
  > & {
    confidence: 0.8;
  },
) {
  const distribution = normalizeNumericCdfDistribution({
    distribution: forecast.distribution,
    min: -2,
    max: 15,
    decimals: 1,
  });
  const summary = summarizeNumericCdfDistribution(distribution);

  return {
    ...forecast,
    ...summary,
    distribution,
    confidence: 0.8 as const,
  };
}

function normalizeUsdBillionsForecast(
  forecast: Omit<
    CtcExpansionForecast,
    "confidence" | "pointEstimate" | "ciLow" | "ciHigh"
  > & {
    confidence: 0.8;
  },
) {
  const distribution = normalizeNumericCdfDistribution({
    distribution: forecast.distribution,
    min: 0,
    max: 500,
    decimals: 1,
  });
  const summary = summarizeNumericCdfDistribution(distribution);

  return {
    ...forecast,
    ...summary,
    distribution,
    confidence: 0.8 as const,
  };
}

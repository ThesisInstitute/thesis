import {
  CPI_MARKET_SLUG,
  CPI_SERIES_ID,
  CPI_TARGET_YEAR,
  formatCpiSummary,
} from "@/lib/bls";
import { optionsResponse } from "@/lib/cors";
import {
  formatSpmChildPovertySummary,
  policySnapshotFromPolicy,
  SPM_CHILD_POVERTY_2025_SLUG,
  SPM_TARGET_YEAR,
  unavailablePolicySnapshot,
} from "@/lib/census";
import {
  DATA_POINT_IDS,
  getDataPointSnapshot,
  serializeDataPointSnapshot,
} from "@/lib/data-points";
import {
  generateCpiForecast,
  generateCtcExpansionForecast,
  generateSpmChildPovertyForecast,
} from "@/lib/forecast";
import {
  CTC_3000_FULLY_REFUNDABLE_POLICY_ID,
  CTC_CURRENT_LAW_OUTLAYS_SLUG,
  CTC_EXPANSION_COST_SLUG,
  CTC_TARGET_YEAR,
  CURRENT_LAW_POLICY_ID,
  fetchCtcExpansionDataset,
  fetchPolicy,
  formatCtcExpansionSummary,
  serializeEconomyToolResult,
  serializePolicyToolResult,
} from "@/lib/policyengine";
import { createSseResponse, pause, type SendEvent } from "@/lib/sse";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function OPTIONS(request: Request) {
  return optionsResponse(request);
}

export async function GET(
  request: Request,
  context: { params: Promise<{ slug: string }> },
) {
  const { slug } = await context.params;
  if (slug === CPI_MARKET_SLUG) {
    return createSseResponse(request, async (send) => {
      await streamCpiForecast(send);
    });
  }

  if (slug === CTC_EXPANSION_COST_SLUG) {
    return createSseResponse(request, async (send) => {
      await streamCtcExpansionForecast(send);
    });
  }

  if (slug === CTC_CURRENT_LAW_OUTLAYS_SLUG) {
    return createSseResponse(request, async () => {
      throw new Error(
        "No forecast is available for current-law CTC outlays: the absolute outlay calculation is not implemented.",
      );
    });
  }

  if (slug === SPM_CHILD_POVERTY_2025_SLUG) {
    return createSseResponse(request, async (send) => {
      await streamSpmChildPovertyForecast(send);
    });
  }

  return Response.json(
    { error: `No live forecaster is configured for ${slug}.` },
    { status: 404 },
  );
}

async function streamSpmChildPovertyForecast(send: SendEvent) {
  await sendStep(send, {
    kind: "heading",
    text: "Identifying the question",
  });
  await sendStep(send, {
    kind: "text",
    text: "This stream forecasts the calendar-year 2025 Supplemental Poverty Measure child poverty rate that Census is expected to publish in the September 2026 income and poverty release. The live run checks the PolicyEngine current-law policy and Census pages. Historical values and the calibration prior are stored inputs, not a fresh microsimulation.",
  });

  const policyCall = `policyengine.policy.get({ id: ${CURRENT_LAW_POLICY_ID} })`;
  send("status", {
    state: "tool_running",
    label: "Querying PolicyEngine current law",
  });
  send("tool_start", {
    tool: "policyengine.policy",
    call: policyCall,
  });

  const currentLawPolicy = await fetchPolicy(CURRENT_LAW_POLICY_ID)
    .then((policy) => {
      send("tool_result", {
        tool: "policyengine.policy",
        call: policyCall,
        result: serializePolicyToolResult(policy),
      });
      return policySnapshotFromPolicy(policy);
    })
    .catch((error: unknown) => {
      const snapshot = unavailablePolicySnapshot(CURRENT_LAW_POLICY_ID, error);
      send("tool_result", {
        tool: "policyengine.policy",
        call: policyCall,
        result: JSON.stringify(snapshot, null, 2),
      });
      return snapshot;
    });

  const censusCall = [
    `census.releaseSchedule({ survey: "CPS ASEC", targetYear: ${SPM_TARGET_YEAR}, measure: "SPM child poverty" })`,
    'census.spm.history({ population: "children_under_18", years: [2021, 2024] })',
  ].join("\n");
  send("status", {
    state: "tool_running",
    label: "Running public data-point processor",
  });
  send("tool_start", {
    tool: "data-point.processor",
    call: censusCall,
  });

  const dataPoint = await getDataPointSnapshot(
    DATA_POINT_IDS.SPM_CHILD_POVERTY_RATE_2025,
    { currentLawPolicy },
  );
  const dataset = dataPoint.dataset;

  send("tool_result", {
    tool: "data-point.processor",
    call: censusCall,
    result: serializeDataPointSnapshot(dataPoint),
  });
  await pause(180);

  await sendStep(send, {
    kind: "heading",
    text: "Census and current-law read",
  });
  await sendStep(send, {
    kind: "text",
    text: formatSpmChildPovertySummary(dataset.summary),
  });

  await sendStep(send, {
    kind: "heading",
    text: "Stored calibration prior",
  });
  await sendStep(send, {
    kind: "math",
    text: [
      "Stored prior = ",
      `${dataset.summary.calibration.policyEngineWeight.toFixed(2)} × ${dataset.summary.policyEnginePriorPct.toFixed(1)}% + `,
      `${dataset.summary.calibration.postExpansionHistoryWeight.toFixed(2)} × ${dataset.summary.postExpansionAveragePct.toFixed(1)}% + `,
      `${dataset.summary.calibration.latestPublishedWeight.toFixed(2)} × ${dataset.summary.latestHistoricalChildPovertyRatePct.toFixed(1)}% `,
      `${dataset.summary.calibration.macroAdjustmentPct >= 0 ? "+" : "-"} ${Math.abs(dataset.summary.calibration.macroAdjustmentPct).toFixed(2)}pp = `,
      `${dataset.summary.calibratedPointEstimatePct.toFixed(1)}%`,
    ].join(""),
  });
  await sendStep(send, {
    kind: "text",
    text: "These weights and the PolicyEngine poverty seed are stored prototype assumptions. The live policy check does not run a poverty simulation, and the calibration prior is not a completed forecast.",
  });

  send("status", {
    state: "model_running",
    label: "Generating calibrated forecast",
  });
  await sendStep(send, {
    kind: "heading",
    text: "Forecast model",
  });

  const forecast = await generateSpmChildPovertyForecast(dataset);
  for (const trace of forecast.publicTrace) {
    await sendStep(send, {
      kind: "text",
      text: trace,
    });
  }

  if (forecast.assumptions.length > 0) {
    await sendStep(send, {
      kind: "heading",
      text: "Assumptions and caveats",
    });
    await sendStep(send, {
      kind: "text",
      text: [
        ...forecast.assumptions.map(
          (assumption) => `Assumption: ${assumption}`,
        ),
        ...forecast.dataCaveats.map((caveat) => `Caveat: ${caveat}`),
      ].join(" "),
    });
  }

  send("forecast", forecast);
  send("status", {
    state: "complete",
    label: "AI Gateway forecast complete",
  });
  send("done", { ok: true });
}

async function streamCpiForecast(send: SendEvent) {
  await sendStep(send, {
    kind: "heading",
    text: "Identifying the question",
  });
  await sendStep(send, {
    kind: "text",
    text: "This stream forecasts annual-average CPI-U inflation for calendar year 2026 versus the 2025 annual average. The live run starts from BLS series CUUR0000SA0 and computes current-year annual-average pressure from monthly observations.",
  });

  const call = `bls.timeseries({ series: "${CPI_SERIES_ID}", startYear: ${
    CPI_TARGET_YEAR - 7
  }, endYear: ${CPI_TARGET_YEAR} })`;

  send("status", {
    state: "tool_running",
    label: "Running public data-point processor",
  });
  send("tool_start", {
    tool: "data-point.processor",
    call,
  });

  const dataPoint = await getDataPointSnapshot(
    DATA_POINT_IDS.CPI_U_ANNUAL_PCT_CHANGE_2026,
  );
  const dataset = dataPoint.dataset;

  send("tool_result", {
    tool: "data-point.processor",
    call,
    result: serializeDataPointSnapshot(dataPoint),
  });
  await pause(180);

  await sendStep(send, {
    kind: "heading",
    text: "Live CPI-U read",
  });
  await sendStep(send, {
    kind: "text",
    text: formatCpiSummary(dataset.summary),
  });

  send("status", {
    state: "model_running",
    label: "Generating calibrated forecast",
  });
  await sendStep(send, {
    kind: "heading",
    text: "Forecast model",
  });

  const forecast = await generateCpiForecast(dataset);
  for (const trace of forecast.publicTrace) {
    await sendStep(send, {
      kind: "text",
      text: trace,
    });
  }

  if (forecast.assumptions.length > 0) {
    await sendStep(send, {
      kind: "heading",
      text: "Assumptions and caveats",
    });
    await sendStep(send, {
      kind: "text",
      text: [
        ...forecast.assumptions.map(
          (assumption) => `Assumption: ${assumption}`,
        ),
        ...forecast.dataCaveats.map((caveat) => `Caveat: ${caveat}`),
      ].join(" "),
    });
  }

  send("forecast", forecast);
  send("status", {
    state: "complete",
    label: "AI Gateway forecast complete",
  });
  send("done", { ok: true });
}

async function streamCtcExpansionForecast(send: SendEvent) {
  await sendStep(send, {
    kind: "heading",
    text: "Identifying the question",
  });
  await sendStep(send, {
    kind: "text",
    text: "This stream forecasts the federal budget cost of a $3,000 fully refundable Child Tax Credit in tax year 2026, relative to current law. PolicyEngine supplies the raw microsimulation input; the forecast layer then adjusts that raw model output using an explicit calibration prior.",
  });

  const policyEngineCall = [
    `policyengine.policy.get({ id: ${CURRENT_LAW_POLICY_ID} })`,
    `policyengine.policy.get({ id: ${CTC_3000_FULLY_REFUNDABLE_POLICY_ID} })`,
    `policyengine.economy({ policy: ${CTC_3000_FULLY_REFUNDABLE_POLICY_ID}, baseline: ${CURRENT_LAW_POLICY_ID}, region: "us", time_period: ${CTC_TARGET_YEAR} })`,
  ].join("\n");

  send("status", {
    state: "tool_running",
    label: "Querying PolicyEngine API",
  });
  send("tool_start", {
    tool: "policyengine.api",
    call: policyEngineCall,
  });

  const dataset = await fetchCtcExpansionDataset();

  send("tool_result", {
    tool: "policyengine.api",
    call: policyEngineCall,
    result: [
      "baseline policy:",
      serializePolicyToolResult(dataset.baselinePolicy),
      "reform policy:",
      serializePolicyToolResult(dataset.reformPolicy),
      "economy impact:",
      serializeEconomyToolResult(dataset.economy),
    ].join("\n"),
  });
  await pause(180);

  await sendStep(send, {
    kind: "heading",
    text: "Raw PolicyEngine estimate",
  });
  await sendStep(send, {
    kind: "text",
    text: formatCtcExpansionSummary(dataset.summary),
  });

  await sendStep(send, {
    kind: "heading",
    text: "Stored calibration prior",
  });
  await sendStep(send, {
    kind: "math",
    text: `Stored prior = raw_or_prior × ${dataset.calibration.rawToFinalRatio.toFixed(2)} + $${dataset.calibration.additiveUsdBillions.toFixed(1)}B = $${dataset.summary.calibratedPointEstimateUsdBillions.toFixed(1)}B`,
  });
  await sendStep(send, {
    kind: "text",
    text: "The adjustment weights are stored prototype assumptions, not an observed backtest. When no economy result is available, this input uses a stored prior rather than a fresh simulation. Only a successful model response produces a forecast.",
  });

  send("status", {
    state: "model_running",
    label: "Generating calibrated forecast",
  });
  await sendStep(send, {
    kind: "heading",
    text: "Forecast model",
  });

  const forecast = await generateCtcExpansionForecast(dataset);
  for (const trace of forecast.publicTrace) {
    await sendStep(send, {
      kind: "text",
      text: trace,
    });
  }

  if (forecast.assumptions.length > 0) {
    await sendStep(send, {
      kind: "heading",
      text: "Assumptions and caveats",
    });
    await sendStep(send, {
      kind: "text",
      text: [
        ...forecast.assumptions.map(
          (assumption) => `Assumption: ${assumption}`,
        ),
        ...forecast.dataCaveats.map((caveat) => `Caveat: ${caveat}`),
      ].join(" "),
    });
  }

  send("forecast", forecast);
  send("status", {
    state: "complete",
    label: "AI Gateway forecast complete",
  });
  send("done", { ok: true });
}

async function sendStep(
  send: SendEvent,
  step:
    | { kind: "heading"; text: string }
    | { kind: "text"; text: string }
    | { kind: "math"; text: string },
) {
  send("step", step);
  await pause(step.kind === "heading" ? 180 : 260);
}

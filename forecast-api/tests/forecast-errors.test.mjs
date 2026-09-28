import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";

const generateObject = mock(async () => ({ object: validOutput() }));
mock.module("ai", () => ({ generateObject }));

const actualPolicy = await import("../src/lib/policyengine.ts");
const actualSse = await import("../src/lib/sse.ts");
const { buildNumericCdfFromInterval } =
  await import("../src/lib/prediction-distribution.ts");
const policy = {
  id: 2,
  label: "Test current law",
  api_version: "test",
  policy_json: {},
};
const calibration = {
  rawToFinalRatio: 1,
  additiveUsdBillions: 0,
  policyEngineWeight: 0.5,
  postExpansionHistoryWeight: 0.4,
  latestPublishedWeight: 0.1,
  macroAdjustmentPct: 0,
};
const dataset = {
  summary: {
    question: "Test forecast question",
    latest: { periodName: "May", year: 2026, value: 320 },
    targetYear: 2026,
    priorYear: 2025,
    targetYearMonths: 5,
    targetYtdAverage: 315,
    targetYtdVsPriorObservedAveragePct: 2,
    carryForwardAnnualAverageInflationPct: 2,
    recentAnnualizedPct: 2,
    currentLawPolicy: { status: "ok", id: 2, label: "Test current law" },
    latestHistoricalYear: 2024,
    latestHistoricalChildPovertyRatePct: 13.4,
    postExpansionAveragePct: 13.2,
    policyEnginePriorPct: 13,
    calibratedPointEstimatePct: 13.1,
    calibratedPointEstimateUsdBillions: 100,
    rawPolicyEngineEstimateUsdBillions: 100,
    calibration,
  },
  baselinePolicy: policy,
  reformPolicy: { ...policy, id: 29093 },
  economy: { status: "ok", result: {}, budgetaryImpactUsdBillions: 100 },
  calibration,
};
const fetchPolicy = mock(async () => policy);
const fetchCtcExpansionDataset = mock(async () => dataset);
const getDataPointSnapshot = mock(async () => ({ dataset }));
mock.module("../src/lib/policyengine.ts", () => ({
  ...actualPolicy,
  fetchPolicy,
  fetchCtcExpansionDataset,
}));
mock.module("../src/lib/data-points.ts", () => ({
  DATA_POINT_IDS: {
    CPI_U_ANNUAL_PCT_CHANGE_2026: "cpi-test",
    SPM_CHILD_POVERTY_RATE_2025: "spm-test",
  },
  getDataPointSnapshot,
  serializeDataPointSnapshot: JSON.stringify,
}));
mock.module("../src/lib/sse.ts", () => ({
  ...actualSse,
  pause: async () => {},
}));
const generators = await import("../src/lib/forecast.ts");
const { GET } = await import("../src/app/forecasts/[slug]/stream/route.ts");

const envNames = [
  "AI_GATEWAY_API_KEY",
  "VERCEL_OIDC_TOKEN",
  "VERCEL",
  "BRIER_DISABLE_AI",
];
const originalEnvironment = Object.fromEntries(
  envNames.map((name) => [name, process.env[name]]),
);

beforeEach(() => {
  for (const name of envNames) delete process.env[name];
  generateObject.mockClear();
  generateObject.mockImplementation(async () => ({ object: validOutput() }));
  fetchPolicy.mockClear();
  fetchCtcExpansionDataset.mockClear();
  getDataPointSnapshot.mockClear();
});
afterEach(() => {
  for (const [name, value] of Object.entries(originalEnvironment)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
});

function validOutput() {
  return {
    distribution: buildNumericCdfFromInterval({
      pointEstimate: 5,
      ciLow: 4,
      ciHigh: 6,
      provenance: "agent_reported",
    }),
    publicTrace: [
      "The model used the observed reference class.",
      "The model reported an explicit estimate mechanism.",
      "The model identified a disconfirming consideration.",
    ],
    assumptions: ["First model assumption.", "Second model assumption."],
    dataCaveats: ["Model reported data caveat."],
    drivers: ["First driver", "Second driver"],
  };
}

function enableTestGateway() {
  // Exercise the hosted-runtime branch without creating or reading credentials.
  process.env.VERCEL = "1";
}

async function streamEvents(slug) {
  const response = await GET(
    new Request(`http://localhost/forecasts/${slug}/stream`),
    { params: Promise.resolve({ slug }) },
  );
  return (await response.text())
    .trim()
    .split("\n\n")
    .map((block) => {
      const [event, data] = block.split("\n");
      return {
        event: event.slice("event: ".length),
        data: JSON.parse(data.slice("data: ".length)),
      };
    });
}

const targets = [
  ["CPI", "generateCpiForecast", "cpi-u-annual-2026"],
  [
    "CTC expansion",
    "generateCtcExpansionForecast",
    "ctc-expansion-cost-ty2026",
  ],
  ["SPM", "generateSpmChildPovertyForecast", "spm-child-poverty-2025"],
];

for (const [label, functionName, slug] of targets) {
  describe(label, () => {
    const generate = generators[functionName];

    test("missing credentials reject without a substitute estimate", async () => {
      await expect(generate(dataset)).rejects.toThrow(
        "AI Gateway credentials are not configured",
      );
      expect(generateObject).not.toHaveBeenCalled();
    });

    test("explicitly disabled AI rejects without a substitute estimate", async () => {
      enableTestGateway();
      process.env.BRIER_DISABLE_AI = "1";
      await expect(generate(dataset)).rejects.toThrow(
        "AI forecasting is disabled",
      );
      expect(generateObject).not.toHaveBeenCalled();
    });

    test("successful output keeps the model's public explanation", async () => {
      enableTestGateway();
      const result = await generate(dataset);
      expect(result.source).toBe("ai_gateway");
      expect(result.pointEstimate).toBe(5);
      expect(result.publicTrace).toEqual(validOutput().publicTrace);
      expect(generateObject).toHaveBeenCalledTimes(1);
    });

    for (const failure of [
      "missing credentials",
      "access denied",
      "invalid response",
    ]) {
      test(`${failure} ends the stream as failed without a forecast`, async () => {
        if (failure !== "missing credentials") enableTestGateway();
        if (failure === "access denied") {
          generateObject.mockRejectedValue(new Error("Model access denied"));
        }
        if (failure === "invalid response") {
          generateObject.mockResolvedValue({
            object: { publicTrace: ["invalid"] },
          });
        }
        const events = await streamEvents(slug);
        expect(events.some((item) => item.event === "forecast")).toBe(false);
        expect(events.filter((item) => item.event === "failure")).toHaveLength(
          1,
        );
        expect(events.filter((item) => item.event === "done")).toEqual([
          { event: "done", data: { ok: false } },
        ]);
        expect(events.some((item) => item.data.state === "complete")).toBe(
          false,
        );
        expect(
          events.some((item) => item.data.tool === "brier.calibration"),
        ).toBe(false);
        expect(generateObject).toHaveBeenCalledTimes(
          failure === "missing credentials" ? 0 : 1,
        );
        const failureEvent = events.find((item) => item.event === "failure");
        if (failure === "missing credentials") {
          expect(failureEvent.data.message).toContain(
            "credentials are not configured",
          );
        }
        if (failure === "invalid response") {
          expect(failureEvent.data.message).toContain("AI forecast failed");
        }
        if (failure === "access denied") {
          expect(failureEvent.data.message).toContain("Model access denied");
        }
      });
    }

    test("a successful model run still emits one forecast and succeeds", async () => {
      enableTestGateway();
      const events = await streamEvents(slug);
      expect(events.filter((item) => item.event === "forecast")).toHaveLength(
        1,
      );
      expect(events.some((item) => item.event === "failure")).toBe(false);
      expect(events.at(-1)).toEqual({ event: "done", data: { ok: true } });
    });
  });
}

test("unimplemented current-law CTC outlays fail before tools or model calls", async () => {
  enableTestGateway();
  const events = await streamEvents("ctc-current-law-outlays-ty2026");
  expect(events).toEqual([
    {
      event: "failure",
      data: {
        message:
          "No forecast is available for current-law CTC outlays: the absolute outlay calculation is not implemented.",
      },
    },
    { event: "done", data: { ok: false } },
  ]);
  expect(fetchPolicy).not.toHaveBeenCalled();
  expect(fetchCtcExpansionDataset).not.toHaveBeenCalled();
  expect(getDataPointSnapshot).not.toHaveBeenCalled();
  expect(generateObject).not.toHaveBeenCalled();
});

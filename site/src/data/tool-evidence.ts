/** Public projection of runner-captured evidence; never supplied by model cells. */
export interface CapturedToolCall {
  callId: string;
  tool: "fetch_source" | "extract_json" | "calculate";
  arguments: Record<string, unknown>;
  startedAt: string;
  completedAt: string;
  status: "succeeded" | "failed";
  result: unknown;
  error?: string;
  response?: {
    url: string;
    status: number;
    headers: [string, string][];
    sha256: string;
    bytes: number;
    bodyText?: string;
    bodyTextTruncated?: boolean;
  };
  replay: "captured" | "replayed" | "failed";
  replayChecks: string[];
}

export interface CapturedToolEvidence {
  stage: "forecast" | "draft" | "review";
  artifactPath: string;
  artifactSha256: string;
  verificationPath: string;
  calls: CapturedToolCall[];
}

export type ForecastToolEvidence =
  | { status: "missing" }
  | { status: "invalid" }
  | { status: "available"; artifacts: CapturedToolEvidence[] };

export type ForecastToolEvidenceByVariant = Record<
  string,
  ForecastToolEvidence
>;

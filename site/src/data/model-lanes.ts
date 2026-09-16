/**
 * Display registry for the recorded protocol lanes.
 *
 * A lane is a DERIVED attribute of the records: the batch's promptMode plus
 * the suite-level derivations (median3, system_one). Nothing here decides
 * which lanes exist. The order below is a reading order and the labels are
 * display names; neither is an allowlist. A lane recorded under a token this
 * file does not know still renders, under that raw token, so a new lane never
 * silently vanishes from the table (the System One lane landing in 2026-09 is
 * the motivating case: a fixed lane filter would have dropped every one of
 * its runs from /models without failing a build).
 */
export const MODEL_LANE_ORDER: string[] = [
  "fast",
  "ladder",
  "ladder_v2",
  "median3",
  "system_one",
];

export const MODEL_LANE_LABELS: Record<string, string> = {
  fast: "Fast",
  ladder: "Ladder",
  ladder_v2: "Ladder v2",
  median3: "Median-of-3",
  system_one: "System One",
};

export function modelLaneLabel(lane: string): string {
  return MODEL_LANE_LABELS[lane] ?? lane;
}

/** Known lanes in reading order, then anything else alphabetically. */
export function orderModelLanes(lanes: Iterable<string>): string[] {
  const present = new Set(lanes);
  return [
    ...MODEL_LANE_ORDER.filter((lane) => present.has(lane)),
    ...[...present].filter((lane) => !MODEL_LANE_ORDER.includes(lane)).sort(),
  ];
}

import { describe, expect, it } from "vitest";
import { MODEL_LANE_STATS } from "@/data/model-lane-stats.generated";
import {
  MODEL_LANE_LABELS,
  MODEL_LANE_ORDER,
  modelLaneLabel,
  orderModelLanes,
} from "@/data/model-lanes";

// The /models table used to filter recorded lanes through a fixed list, so a
// lane the publisher started writing (System One, 2026-09) would have been
// dropped from the page with no build failure and no empty column to notice.
// The registry is an ordering plus display names now, and these tests hold it
// to that: nothing recorded may disappear.
describe("model lane registry", () => {
  it("registers both System One elicitations with display labels", () => {
    expect(MODEL_LANE_ORDER).toContain("system_one_noul_ladder");
    expect(MODEL_LANE_ORDER).toContain("system_one_choice_bins");
    expect(MODEL_LANE_LABELS.system_one_noul_ladder).toBe("System One ladder");
    expect(MODEL_LANE_LABELS.system_one_choice_bins).toBe("System One bins");
    expect(modelLaneLabel("system_one_choice_bins")).toBe("System One bins");
  });

  it("orders known lanes first and keeps unknown lanes visible", () => {
    const ordered = orderModelLanes([
      "zzz_future_lane",
      "system_one_choice_bins",
      "system_one_noul_ladder",
      "fast",
      "aaa_future_lane",
    ]);

    expect(ordered).toEqual([
      "fast",
      "system_one_noul_ladder",
      "system_one_choice_bins",
      "aaa_future_lane",
      "zzz_future_lane",
    ]);
    // An unlabeled lane renders under its own token rather than blank.
    expect(modelLaneLabel("zzz_future_lane")).toBe("zzz_future_lane");
  });

  it("never drops a lane that the records already carry", () => {
    const recorded = [...new Set(MODEL_LANE_STATS.map((row) => row.lane))];
    expect(recorded.length).toBeGreaterThan(0);
    const ordered = orderModelLanes(recorded);
    expect([...ordered].sort()).toEqual([...recorded].sort());
  });

  it("labels every lane it claims to know", () => {
    for (const lane of MODEL_LANE_ORDER) {
      expect(MODEL_LANE_LABELS[lane]).toBeTruthy();
    }
  });
});

import { describe, expect, it } from "vitest";

import { isKnownStage, stageLabelKey } from "./stages";

describe("stage labels", () => {
  it("labels the stages added after Phase 2", () => {
    expect(stageLabelKey("s4b_grid")).toBe("stage.grid");
    expect(stageLabelKey("s7b_rebar")).toBe("stage.rebar");
    expect(stageLabelKey("s7c_align")).toBe("stage.alignRebarred");
  });

  it("labels every stage the pipeline can emit", () => {
    for (const stage of [
      "s0_ingest",
      "s1_route",
      "s3_amt",
      "s4_beats",
      "s5_score",
      "s5_score_fallback",
      "s6_post",
      "s7_align",
      "s8_render",
    ]) {
      expect(isKnownStage(stage)).toBe(true);
    }
  });

  it("leaves an unknown stage unlabelled instead of hiding it", () => {
    expect(isKnownStage("s9_new")).toBe(false);
    expect(stageLabelKey("s9_new")).toBe("");
  });
});

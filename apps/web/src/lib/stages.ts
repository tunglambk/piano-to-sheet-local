/**
 * Stage labels for the processing view.
 *
 * The pipeline gained stages after Phase 2 (`s4b_grid`, `s7b_rebar`, `s7c_align`),
 * and showing raw ids to a user is noise. Every stage maps to a translation key;
 * an unknown stage falls back to its id so a new stage is visible before its label
 * lands (D-047).
 */

export const STAGE_LABELS: Record<string, string> = {
  s0_ingest: "stage.ingest",
  s1_route: "stage.route",
  s3_amt: "stage.transcribe",
  s4_beats: "stage.beats",
  s4b_grid: "stage.grid",
  s5_score: "stage.score",
  s5_score_fallback: "stage.scoreFallback",
  s6_post: "stage.post",
  s7_align: "stage.align",
  s7b_rebar: "stage.rebar",
  s7c_align: "stage.alignRebarred",
  s8_render: "stage.render",
};

export function stageLabelKey(stage: string): string {
  return STAGE_LABELS[stage] ?? "";
}

export function isKnownStage(stage: string): boolean {
  return stage in STAGE_LABELS;
}

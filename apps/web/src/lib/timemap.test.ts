import { describe, expect, it } from "vitest";
import { currentMeasure, measureWindow, notesInMeasure, seekTarget } from "./timemap";
import type { Timemap } from "../api";

const timemap: Timemap = {
  notes: { a: [0.0, 0.4], b: [1.1, 1.4], c: [2.2, 2.6] },
  measures: [
    { measure: 1, onset_s: 0 },
    { measure: 2, onset_s: 1.0 },
    { measure: 3, onset_s: 2.0 },
  ],
  n_notes: 3,
};

describe("timemap", () => {
  it("finds the measure playing at a time", () => {
    expect(currentMeasure(timemap, 0)).toBe(1);
    expect(currentMeasure(timemap, 0.99)).toBe(1);
    expect(currentMeasure(timemap, 1.0)).toBe(2);
    expect(currentMeasure(timemap, 5)).toBe(3);
  });

  it("returns the window and the notes of a measure", () => {
    expect(measureWindow(timemap, 2)).toEqual([1.0, 2.0]);
    expect(notesInMeasure(timemap, 2)).toEqual(["b"]);
    expect(seekTarget(timemap, 3)).toBe(2.0);
  });
});

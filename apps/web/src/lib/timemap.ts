import type { Timemap } from "../api";

export function currentMeasure(timemap: Timemap, seconds: number): number | null {
  const measures = timemap.measures;
  if (!measures.length) return null;
  let low = 0;
  let high = measures.length - 1;
  let answer = measures[0].measure;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (measures[mid].onset_s <= seconds) {
      answer = measures[mid].measure;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return answer;
}

export function measureWindow(timemap: Timemap, measure: number): [number, number] {
  const index = timemap.measures.findIndex((entry) => entry.measure === measure);
  if (index < 0) return [0, 0];
  const start = timemap.measures[index].onset_s;
  const end = index + 1 < timemap.measures.length ? timemap.measures[index + 1].onset_s : start + 2;
  return [start, end];
}

export function notesInMeasure(timemap: Timemap, measure: number): string[] {
  const [start, end] = measureWindow(timemap, measure);
  return Object.entries(timemap.notes)
    .filter(([, [onset]]) => onset >= start - 1e-6 && onset < end - 1e-6)
    .map(([id]) => id);
}

export function seekTarget(timemap: Timemap, measure: number): number {
  return measureWindow(timemap, measure)[0];
}

/** Parse a score entered by a user without dropping its fractional part. */
export function parseScore(value: string): number {
  return value === "" ? 0 : Number.parseFloat(value);
}

/** Avoid exposing floating-point arithmetic artifacts such as 0.30000000000000004. */
export function formatScore(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return Number(value.toFixed(10)).toString();
}

export function sumScores(values: Array<number | string>): number {
  const total = values.reduce<number>(
    (sum, value) => sum + (typeof value === "number" && Number.isFinite(value) ? value : 0),
    0,
  );
  return Number(total.toFixed(10));
}

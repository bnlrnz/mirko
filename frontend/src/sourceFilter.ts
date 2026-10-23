/**
 * The agenda stores multiple contributing companies in one comma-separated
 * field. The source filter works on individual company names instead.
 */
export function splitSourceCompanies(
  value: string | null | undefined,
): string[] {
  if (!value) {
    return [];
  }
  return value
    .split(",")
    .map((company) => company.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

/** Build a stable, case-insensitively deduplicated list of company names. */
export function uniqueSourceCompanies(
  values: Iterable<string | null | undefined>,
): string[] {
  const companies = new Map<string, string>();
  for (const value of values) {
    for (const company of splitSourceCompanies(value)) {
      const key = company.toLocaleLowerCase();
      if (!companies.has(key)) {
        companies.set(key, company);
      }
    }
  }
  return [...companies.values()].sort((left, right) =>
    left.localeCompare(right),
  );
}

export function sourceMatches(
  selected: string,
  value: string | null | undefined,
): boolean {
  const wanted = selected.trim().toLocaleLowerCase();
  return splitSourceCompanies(value).some(
    (company) => company.toLocaleLowerCase() === wanted,
  );
}

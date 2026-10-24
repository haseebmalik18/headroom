/** Short, readable labels from the model's long titles and pytest ids. */

export function shortTitle(title: string): string {
  const cut = title.split(/,|;| — | - /)[0].replace(/\s*\([^)]*\)/g, "").trim();
  return cut.length > 64 ? `${cut.slice(0, 61).trimEnd()}…` : cut;
}

export const humanizeTest = (id: string) => (id.split("::").at(-1) ?? id).replace(/^test_/, "").replace(/_/g, " ");

const BUSINESS_FAILURES: [RegExp, string][] = [
  [/concurrent_reservations_never_oversell/, "it oversold inventory under concurrent checkout"],
  [/concurrent_mixed_quantities_conserve_stock/, "it lost inventory consistency under concurrent checkout"],
  [/concurrent_reservations_across_skus_conserve_stock/, "it corrupted stock totals across simultaneous checkouts"],
  [/responses_report_consistent_remaining_stock/, "it returned inconsistent remaining stock"],
  [/wrong_password_is_rejected/, "it accepted an invalid password"],
  [/password_change_requires_the_old_password/, "it changed a password without verifying the old one"],
];

/** Turn a pytest id into the user-visible consequence of accepting that patch. */
export function explainTestFailure(id: string): string {
  return BUSINESS_FAILURES.find(([pattern]) => pattern.test(id))?.[1]
    ?? `the test “${humanizeTest(id)}” failed`;
}

export function firstSentence(text: string, max = 150): string {
  const s = text.split(/(?<=\.)\s/)[0];
  return s.length > max ? `${s.slice(0, max - 1).trimEnd()}…` : s;
}

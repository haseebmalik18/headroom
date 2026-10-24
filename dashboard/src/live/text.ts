/** Short, readable labels from the model's long titles and pytest ids. */

export function shortTitle(title: string): string {
  const cut = title.split(/,|;| — | - /)[0].replace(/\s*\([^)]*\)/g, "").trim();
  return cut.length > 64 ? `${cut.slice(0, 61).trimEnd()}…` : cut;
}

export const humanizeTest = (id: string) => (id.split("::").at(-1) ?? id).replace(/^test_/, "").replace(/_/g, " ");

export function firstSentence(text: string, max = 150): string {
  const s = text.split(/(?<=\.)\s/)[0];
  return s.length > max ? `${s.slice(0, max - 1).trimEnd()}…` : s;
}

/** The text value of a form field. File inputs and missing fields yield an empty string. */
export function fieldText(form: HTMLFormElement, name: string): string {
  const value = new FormData(form).get(name);
  return typeof value === "string" ? value : "";
}

// Phosphor ships every icon in six weights, and the app draws a few of them. This build step
// keeps in each icon only the weights the source code names, so the others never reach the
// bundle. A weight the build cannot read from the source fails the build instead of leaving an
// icon empty on screen.

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import type { Plugin } from "vite";

export const WEIGHTS = ["thin", "light", "regular", "bold", "fill", "duotone"] as const;
const DEFAULT_WEIGHT = "regular";
const DEFINITION = /@phosphor-icons\/react\/dist\/defs\/\w+\.es\.js$/;
// A weight as written in the source: a literal, or a choice between two literals.
const LITERAL = /^"(\w+)"$/;
const CHOICE = /^\{[^{}?]*\?\s*"(\w+)"\s*:\s*"(\w+)"\s*\}$/;

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return entry.name === "paraglide" ? [] : sourceFiles(path);
    return /\.tsx?$/.test(entry.name) && !entry.name.includes(".test.") ? [path] : [];
  });
}

/** Every weight an icon is given in ``text``; throws on one written any other way. */
export function weightsIn(text: string, file: string): string[] {
  const found: string[] = [];
  for (const match of text.matchAll(/\bweight=/g)) {
    const start = match.index + match[0].length;
    let end = start;
    if (text[start] === '"') {
      end = text.indexOf('"', start + 1) + 1;
    } else if (text[start] === "{") {
      end = text.indexOf("}", start) + 1;
    }
    const value = text.slice(start, end).replace(/\s+/g, " ");
    const literal = LITERAL.exec(value);
    const choice = CHOICE.exec(value);
    if (literal) {
      found.push(literal[1]);
    } else if (choice) {
      found.push(choice[1], choice[2]);
    } else {
      const line = text.slice(0, start).split("\n").length;
      throw new Error(
        `${file}:${String(line)}: write an icon's weight as a string literal, or a choice ` +
          `between two, so the build can keep it (got ${value || "nothing"})`,
      );
    }
  }
  return found;
}

/** ``code`` of one icon definition without the weights not in ``keep``. */
export function withWeights(code: string, keep: ReadonlySet<string>): string {
  let result = code;
  for (const weight of WEIGHTS) {
    if (keep.has(weight)) continue;
    const entry = new RegExp(`\\n {2}\\[\\n {4}"${weight}",[\\s\\S]*?\\n {2}\\],?`);
    result = result.replace(entry, "");
  }
  for (const weight of keep) {
    if (!result.includes(`"${weight}"`)) throw new Error(`an icon lost its ${weight} weight`);
  }
  return result;
}

export function phosphorWeights(sourceDirectory: string): Plugin {
  let keep: ReadonlySet<string> = new Set(WEIGHTS);
  return {
    name: "synapse:phosphor-weights",
    apply: "build",
    buildStart() {
      const used = sourceFiles(sourceDirectory).flatMap((file) =>
        weightsIn(readFileSync(file, "utf8"), file),
      );
      const unknown = used.filter((weight) => !(WEIGHTS as readonly string[]).includes(weight));
      if (unknown.length) throw new Error(`not Phosphor weights: ${unknown.join(", ")}`);
      keep = new Set([DEFAULT_WEIGHT, ...used]);
    },
    transform(code, id) {
      return DEFINITION.test(id) ? { code: withWeights(code, keep), map: null } : null;
    },
  };
}

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./App";
import { locales } from "./paraglide/runtime.js";

describe("App", () => {
  it("renders the product name and a language switch", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Synapse");
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("offers exactly Turkish and English", () => {
    expect([...locales].sort()).toEqual(["en", "tr"]);
  });
});

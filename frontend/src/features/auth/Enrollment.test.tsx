import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { m } from "@/paraglide/messages.js";

import { QrCode } from "./QrCode";
import { RecoveryCodes } from "./RecoveryCodes";

describe("QrCode", () => {
  it("draws the code as an accessible SVG image without injected markup", () => {
    render(<QrCode value="otpauth://totp/Synapse:a%40b.org?secret=ABC" label="QR" />);
    const image = screen.getByRole("img", { name: "QR" });
    expect(image).toBeInstanceOf(SVGSVGElement);
    expect(image.querySelector("path")?.getAttribute("d")?.length).toBeGreaterThan(100);
  });
});

describe("RecoveryCodes", () => {
  it("lists every code and continues only when the user confirms", () => {
    const codes = ["AAAA-BBBB-CCCC-DDDD", "EEEE-FFFF-GGGG-HHHH"];
    const onContinue = vi.fn();
    render(<RecoveryCodes codes={codes} onContinue={onContinue} />);
    for (const code of codes) expect(screen.getByText(code)).toBeInTheDocument();
    expect(onContinue).not.toHaveBeenCalled();
    screen.getByRole("button", { name: m.auth_recovery_continue() }).click();
    expect(onContinue).toHaveBeenCalledOnce();
  });
});

describe("RecoveryCodes leaving the page", () => {
  it("asks before the page is unloaded while the codes are shown", () => {
    const { unmount } = render(
      <RecoveryCodes codes={["AAAA-BBBB-CCCC-DDDD"]} onContinue={vi.fn()} />,
    );
    const shown = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(shown);
    expect(shown.defaultPrevented).toBe(true);

    unmount();
    const afterwards = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(afterwards);
    expect(afterwards.defaultPrevented).toBe(false);
  });
});

import { encode } from "uqr";

interface QrCodeProps {
  value: string;
  label: string;
}

/**
 * A QR code drawn as SVG elements by React. The library only computes the module matrix,
 * so no generated markup is ever injected into the page (ADR 0011).
 */
export function QrCode({ value, label }: QrCodeProps) {
  const { size, data } = encode(value, { border: 2 });
  const cells: string[] = [];
  data.forEach((row, y) => {
    row.forEach((dark, x) => {
      if (dark) cells.push(`M${String(x)},${String(y)}h1v1h-1z`);
    });
  });
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${String(size)} ${String(size)}`}
      className="mx-auto size-48 rounded bg-white"
      shapeRendering="crispEdges"
    >
      <path d={cells.join("")} fill="black" />
    </svg>
  );
}

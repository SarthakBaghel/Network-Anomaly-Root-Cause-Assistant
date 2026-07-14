import "@testing-library/jest-dom/vitest";

// Provide ResizeObserver mock for components that rely on it
class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

(global as any).ResizeObserver = ResizeObserver as any;

// Minimal matchMedia mock
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// Mock recharts to avoid ResponsiveContainer measuring issues in JSDOM
import { vi } from "vitest";
import React from "react";

vi.mock("recharts", () => {
  return {
    ResponsiveContainer: ({ children }: any) =>
      React.createElement(
        "div",
        { "data-testid": "recharts-responsive" },
        children,
      ),
    ComposedChart: ({ children }: any) =>
      React.createElement("div", {}, children),
    Scatter: ({ data }: any) =>
      React.createElement(
        "g",
        {},
        Array.isArray(data)
          ? data.map((d: any, i: number) =>
              React.createElement("circle", {
                key: i,
                "data-attached": String(Boolean(d.attached)),
              }),
            )
          : null,
      ),
    Tooltip: () => React.createElement("div", {}),
    XAxis: () => React.createElement("div", {}),
    YAxis: () => React.createElement("div", {}),
    CartesianGrid: () => React.createElement("div", {}),
  };
});

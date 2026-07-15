import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import React from "react";

import { server } from "../src/mocks/server";
import { resetFixtureState } from "../src/test-fixtures/handlers";

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetFixtureState();
});
afterAll(() => server.close());

// Provide ResizeObserver mock for components that rely on it
class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

(globalThis as any).ResizeObserver = ResizeObserver as any;

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

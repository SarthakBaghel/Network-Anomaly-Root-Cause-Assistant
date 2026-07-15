import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./styles.css";

if (import.meta.env.DEV && import.meta.env.VITE_ENABLE_MSW === "true") {
  void import("./mocks/browser").then((module) => module.worker.start());
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

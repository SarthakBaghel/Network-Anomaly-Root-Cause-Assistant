import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./styles.css";

if (import.meta.env.DEV) {
  void import("./mocks/browser").then((module) => module.worker.start());
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

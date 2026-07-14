import { setupWorker } from "msw/browser";
import { handlers } from "../test-fixtures/handlers";

export const worker = setupWorker(...handlers);

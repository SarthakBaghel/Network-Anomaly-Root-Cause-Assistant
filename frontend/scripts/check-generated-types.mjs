import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const directory = mkdtempSync(join(tmpdir(), "network-rca-openapi-"));
const generated = join(directory, "openapi.d.ts");

try {
  execFileSync(
    join(process.cwd(), "node_modules", ".bin", "openapi-typescript"),
    ["../backend/openapi.json", "-o", generated],
    { stdio: "inherit" },
  );
  const expected = readFileSync("src/contracts/openapi.d.ts", "utf8");
  const actual = readFileSync(generated, "utf8");
  if (actual !== expected) {
    throw new Error(
      "src/contracts/openapi.d.ts is stale; run make generate-types",
    );
  }
  console.log("validated generated frontend types against backend/openapi.json");
} finally {
  rmSync(directory, { recursive: true, force: true });
}

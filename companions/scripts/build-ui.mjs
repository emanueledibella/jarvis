import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
const cwd = fileURLToPath(new URL("../../web", import.meta.url));
const result = spawnSync(process.platform === "win32" ? "npm.cmd" : "npm", ["run", "build"], { cwd, stdio: "inherit", shell: process.platform === "win32" });
process.exit(result.status ?? 1);

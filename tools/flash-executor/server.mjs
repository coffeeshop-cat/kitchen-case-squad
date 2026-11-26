import { fileURLToPath } from "node:url";

process.env.FLASH_EXECUTOR_HOME = fileURLToPath(new URL("./", import.meta.url));
await import("./releases/0.2.0/server.mjs");
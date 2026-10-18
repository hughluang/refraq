import { spawn } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const nextBin = path.join(frontendDir, "node_modules/.bin/next");
const port = process.env.E2E_CONSOLE_PORT ?? "4173";
const upstream = process.env.REFRAQ_API_UPSTREAM ?? "http://127.0.0.1:8010";
const buildDir = path.join(frontendDir, ".next");
const standaloneDir = path.join(buildDir, "standalone");
const stampPath = path.join(buildDir, "e2e-upstream");

const env = {
  ...process.env,
  REFRAQ_API_UPSTREAM: upstream,
  NEXT_PUBLIC_REFRAQ_API_BASE_URL:
    process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL ?? "/api",
};

function run(args) {
  return new Promise((resolve, reject) => {
    const child = spawn(nextBin, args, { cwd: frontendDir, env, stdio: "inherit" });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`next ${args.join(" ")} exited ${code}`));
    });
  });
}

const stamped = existsSync(stampPath) ? readFileSync(stampPath, "utf8").trim() : "";
const serverJs = path.join(standaloneDir, "server.js");
if (!existsSync(serverJs) || stamped !== upstream) {
  await run(["build"]);
  writeFileSync(stampPath, `${upstream}\n`);
}

const standaloneNext = path.join(standaloneDir, ".next");
mkdirSync(standaloneNext, { recursive: true });
cpSync(path.join(buildDir, "static"), path.join(standaloneNext, "static"), {
  recursive: true,
});
const publicDir = path.join(frontendDir, "public");
if (existsSync(publicDir)) {
  cpSync(publicDir, path.join(standaloneDir, "public"), { recursive: true });
}

const server = spawn(process.execPath, ["server.js"], {
  cwd: standaloneDir,
  env: {
    ...env,
    NODE_ENV: "production",
    HOSTNAME: "127.0.0.1",
    PORT: port,
  },
  stdio: "inherit",
});

function stop() {
  server.kill("SIGTERM");
}

process.on("SIGTERM", stop);
process.on("SIGINT", stop);
server.on("exit", (code) => process.exit(code ?? 0));

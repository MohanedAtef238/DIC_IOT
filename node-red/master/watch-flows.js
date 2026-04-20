const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const flowFile = process.env.FLOW_FILE;
if (!flowFile) {
  console.error("FLOW_FILE env must be set");
  process.exit(1);
}
const sourcePath = process.env.FLOW_SOURCE || path.join("/data", flowFile);
const targetPath = process.env.FLOW_TARGET || path.join("/data", flowFile);
const pollMs = Number.parseInt(process.env.FLOW_WATCH_INTERVAL_MS || "3000", 10);

let lastDigest = null;
let syncing = false;

function digest(text) {
  return crypto.createHash("sha256").update(text).digest("hex");
}

function ensureParent(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function readText(filePath) {
  return fs.readFileSync(filePath, "utf8");
}

function writeText(filePath, text) {
  ensureParent(filePath);
  fs.writeFileSync(filePath, text);
}

async function waitForEditor() {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      const response = await fetch("http://127.0.0.1:1880/flows", { method: "GET" });
      if (response.ok) return true;
    } catch (_) {
      // Node-RED may still be starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return false;
}

async function reloadFlows(text) {
  const response = await fetch("http://127.0.0.1:1880/flows", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Node-RED-Deployment-Type": "full",
    },
    body: text,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`flow reload failed: ${response.status} ${body}`);
  }
}

async function syncFlows() {
  if (syncing || !fs.existsSync(sourcePath)) return;

  syncing = true;
  try {
    const sourceText = readText(sourcePath);
    const nextDigest = digest(sourceText);
    if (nextDigest === lastDigest) return;

    if (sourcePath !== targetPath) {
      const currentTarget = fs.existsSync(targetPath) ? readText(targetPath) : null;
      if (currentTarget !== sourceText) {
        writeText(targetPath, sourceText);
        console.log(`[watch-flows] synced ${sourcePath} -> ${targetPath}`);
      }

      const credSourcePath = sourcePath.replace(".json", "_cred.json");
      const credTargetPath = targetPath.replace(".json", "_cred.json");
      if (fs.existsSync(credSourcePath)) {
        const credSourceText = readText(credSourcePath);
        const currentCredTarget = fs.existsSync(credTargetPath) ? readText(credTargetPath) : null;
        if (currentCredTarget !== credSourceText) {
          writeText(credTargetPath, credSourceText);
          console.log(`[watch-flows] synced ${credSourcePath} -> ${credTargetPath}`);
        }
      }
    }

    const ready = await waitForEditor();
    if (!ready) {
      console.warn("[watch-flows] Node-RED API not ready; will retry on next poll");
      return;
    }

    lastDigest = nextDigest;
    console.log(`[watch-flows] monitored ${sourcePath} change, reload via API skipped to preserve credentials.`);
  } catch (error) {
    console.warn("[watch-flows] sync failed:", error.message || error);
  } finally {
    syncing = false;
  }
}

setInterval(() => {
  void syncFlows();
}, Number.isNaN(pollMs) ? 3000 : pollMs);

void syncFlows();

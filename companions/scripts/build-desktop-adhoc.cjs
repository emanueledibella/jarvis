"use strict";
const { build, Platform, Arch } = require("electron-builder");

// A runnable local ARM64 build without using a personal signing identity.
// Production entitlements and certificate-based distribution stay separate.
async function main() {
  if (process.platform !== "darwin") throw new Error("This build requires macOS.");
  await build({
    targets: Platform.MAC.createTarget(["dmg", "zip"], process.arch === "arm64" ? Arch.arm64 : Arch.x64),
    config: { mac: {
      identity: "-", notarize: false, hardenedRuntime: true,
      entitlements: "desktop/entitlements.dev.mac.plist",
      entitlementsInherit: "desktop/entitlements.dev.mac.plist",
    } },
  });
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });

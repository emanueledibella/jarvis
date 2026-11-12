"use strict";

// A local development build uses an existing certificate, without notarization
// or changes to the release signing configuration.
const { build, Platform, Arch } = require("electron-builder");
const { signAsync } = require("@electron/osx-sign");

async function main() {
  if (process.platform !== "darwin") throw new Error("This build requires macOS.");
  const identity = process.env.JARVIS_MAC_SIGN_IDENTITY;
  if (!/^[0-9a-f]{40}$/i.test(identity || "")) {
    throw new Error("Set JARVIS_MAC_SIGN_IDENTITY to the SHA-1 fingerprint of an existing Apple Development identity.");
  }
  await build({
    targets: Platform.MAC.createTarget(["dmg", "zip"], process.arch === "arm64" ? Arch.arm64 : Arch.x64),
    config: {
      mac: {
        // Let electron-builder invoke our signer even without a Developer ID.
        identity: "-",
        notarize: false,
        sign: options => signAsync({
          ...options,
          identity,
          identityValidation: false,
          type: "development",
          preAutoEntitlements: false,
          preEmbedProvisioningProfile: false,
          strictVerify: true,
        }),
      },
    },
  });
}

main().catch(error => { console.error(error.message); process.exitCode = 1; });

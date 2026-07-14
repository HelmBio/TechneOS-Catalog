/**
 * postMessage bridge between this App and the platform shell that hosts it.
 *
 * Incoming messages:
 *   { type: "load_molecule", payload: "<MOL block | SMILES>" }
 *   { type: "ping" }
 *
 * Outgoing messages:
 *   { type: "ready" }                       // on init
 *   { type: "pong" }                        // in reply to ping
 *   { type: "molecule_changed", payload: "<MOL block>" }
 *
 * We trust only same-origin messages (the iframe is served from the same
 * origin as the platform shell via the gateway proxy).
 */

import type { Ketcher } from "ketcher-core";

type GetKetcher = () => Ketcher | null;

export function initPlatformBridge(getKetcher: GetKetcher): () => void {
  if (typeof window === "undefined") return () => {};

  const handler = (event: MessageEvent) => {
    if (event.origin !== window.location.origin) return;
    const msg = event.data;
    if (!msg || typeof msg !== "object" || typeof msg.type !== "string") return;
    const ketcher = getKetcher();
    if (msg.type === "ping") {
      window.parent.postMessage({ type: "pong" }, window.location.origin);
      return;
    }
    if (msg.type === "load_molecule" && ketcher && typeof msg.payload === "string") {
      void ketcher.setMolecule(msg.payload);
    }
  };

  window.addEventListener("message", handler);
  // Announce readiness once.
  window.parent.postMessage({ type: "ready" }, window.location.origin);
  return () => window.removeEventListener("message", handler);
}

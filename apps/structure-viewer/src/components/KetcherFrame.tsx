"use client";

import { useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import { StandaloneStructServiceProvider } from "ketcher-standalone";
import "ketcher-react/dist/index.css";
import { initPlatformBridge } from "@/lib/platform-bridge";
import type { Ketcher } from "ketcher-core";

const Editor = dynamic(() => import("ketcher-react").then((m) => m.Editor), {
  ssr: false,
  loading: () => <div style={{ padding: 16 }}>Loading editor…</div>,
});

const structServiceProvider = new StandaloneStructServiceProvider();

export default function KetcherFrame() {
  const ketcherRef = useRef<Ketcher | null>(null);

  useEffect(() => {
    return initPlatformBridge(() => ketcherRef.current);
  }, []);

  return (
    <Editor
      staticResourcesUrl={process.env.APP_BASE_PATH || ""}
      structServiceProvider={structServiceProvider}
      errorHandler={(message: string) => {
        // eslint-disable-next-line no-console
        console.error("Ketcher error:", message);
      }}
      onInit={(ketcher) => {
        ketcherRef.current = ketcher;
        if (typeof window !== "undefined") {
          (window as unknown as { __techneosKetcher: Ketcher }).__techneosKetcher = ketcher;
        }
      }}
    />
  );
}

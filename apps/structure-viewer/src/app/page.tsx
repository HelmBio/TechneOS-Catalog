"use client";

import dynamic from "next/dynamic";

// Lazy-load with ssr: false so the server bundle doesn't drag in
// ketcher-standalone → ketcher-core → paper → jsdom. Those modules
// have side effects at import time (paper instantiates a JSDOM
// instance for measurement when not in a browser) that crash
// prerender even though the component itself is "use client".
const KetcherFrame = dynamic(() => import("@/components/KetcherFrame"), {
  ssr: false,
  loading: () => <div style={{ padding: 16 }}>Loading editor…</div>,
});

export default function Page() {
  return (
    <main style={{ width: "100%", height: "100vh" }}>
      <KetcherFrame />
    </main>
  );
}

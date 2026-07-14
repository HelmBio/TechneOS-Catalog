import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Chemical Structure Viewer",
  description: "View and edit 2D chemical structures",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JA Hedge – AI Trading Dashboard",
  description:
    "AI-powered event contract trading platform with real-time analytics",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[var(--background)] antialiased">
        {children}
      </body>
    </html>
  );
}

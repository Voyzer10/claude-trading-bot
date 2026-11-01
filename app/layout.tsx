import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Trader Bot Dashboard",
  description: "Live view of the paper-trading bot: runner uptime, coins watched, agent decisions and skip reasons.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

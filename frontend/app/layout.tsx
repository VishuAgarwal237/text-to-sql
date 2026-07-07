import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MelodyStream — Ask your data",
  description: "Natural-language BI over the music catalog (text-to-SQL)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

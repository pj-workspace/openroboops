import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OpenRoboOps",
  description: "Open-source robot fleet operations console",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body>{children}</body>
    </html>
  );
}

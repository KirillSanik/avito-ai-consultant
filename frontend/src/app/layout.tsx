import type { Metadata } from "next";

import "./globals.css";
import { Providers } from "./providers";


export const metadata: Metadata = {
  title: "ReviewDesk",
  description: "Платформа проверки домашних работ",
};


export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

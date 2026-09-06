import type { Metadata } from "next";

import "./globals.css";
import { Providers } from "./providers";


export const metadata: Metadata = {
  title: "ReviewDesk — студентам",
  description: "Курсы, домашние задания и результаты обучения",
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

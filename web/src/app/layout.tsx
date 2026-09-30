import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "文枢 · 跨部门文档处理与问答助手",
  description: "面向学校多部门的官方制度文档智能处理与问答系统",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}

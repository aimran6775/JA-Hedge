import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JA Hedge — AI Trading Terminal",
  description:
    "Institutional-grade AI trading platform for Kalshi event contracts",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen antialiased">
        <script
          dangerouslySetInnerHTML={{
            __html: `window.onerror=function(m,s,l,c,e){
              var d=document.getElementById('__js_error');
              if(d)d.textContent='JS Error: '+m+'\\n'+(e&&e.stack||'at '+s+':'+l);
            };
            window.onunhandledrejection=function(ev){
              var d=document.getElementById('__js_error');
              if(d)d.textContent='Unhandled Promise: '+(ev.reason&&ev.reason.message||ev.reason||'unknown');
            };`,
          }}
        />
        <pre
          id="__js_error"
          style={{
            display: "none",
            position: "fixed",
            bottom: 0,
            left: 0,
            right: 0,
            zIndex: 99999,
            background: "#1a0000",
            color: "#ff6666",
            padding: "12px 16px",
            fontSize: 12,
            fontFamily: "monospace",
            whiteSpace: "pre-wrap",
            maxHeight: "30vh",
            overflow: "auto",
            borderTop: "2px solid #ef4444",
          }}
        />
        <script
          dangerouslySetInnerHTML={{
            __html: `document.getElementById('__js_error').style.display='none';
            window.addEventListener('error',function(){document.getElementById('__js_error').style.display='block';});
            window.addEventListener('unhandledrejection',function(){document.getElementById('__js_error').style.display='block';});`,
          }}
        />
        {children}
      </body>
    </html>
  );
}

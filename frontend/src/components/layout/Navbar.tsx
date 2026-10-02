"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquare, BarChart2, CheckCircle2, AlertTriangle, ShieldCheck, Activity } from "lucide-react";
import { checkServerReady } from "@/lib/api-client";

export function Navbar() {
  const pathname = usePathname();
  const [isReady, setIsReady] = useState<boolean>(true);

  useEffect(() => {
    checkServerReady().then(setIsReady);
    const interval = setInterval(() => {
      checkServerReady().then(setIsReady);
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  const navItems = [
    {
      label: "Assistente & Leitor",
      href: "/",
      icon: MessageSquare,
    },
    {
      label: "Scorecard de Avaliação",
      href: "/evals",
      icon: CheckCircle2,
    },
    {
      label: "Métricas & Observabilidade",
      href: "/stats",
      icon: Activity,
    },
  ];

  return (
    <header className="h-14 border-b border-zinc-800 bg-zinc-900/90 px-6 flex items-center justify-between backdrop-blur shrink-0 z-50">
      {/* Brand & Badge */}
      <div className="flex items-center gap-6">
        <Link href="/" className="flex items-center gap-3 group">
          <div className="w-8 h-8 rounded-lg bg-sky-600 flex items-center justify-center font-bold text-white shadow-md group-hover:bg-sky-500 transition-colors">
            P
          </div>
          <div>
            <div className="text-sm font-bold tracking-tight text-zinc-100 flex items-center gap-2">
              PRAG
              <span className="text-[10px] font-mono font-medium px-2 py-0.5 rounded-full bg-sky-950 border border-sky-800 text-sky-400">
                Citações Verificadas
              </span>
            </div>
          </div>
        </Link>

        {/* Desktop Navigation Links */}
        <nav className="hidden md:flex items-center gap-1 border-l border-zinc-800 pl-6">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? "bg-zinc-800 text-sky-400 shadow-sm border border-zinc-700/60"
                    : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40"
                }`}
              >
                <Icon className={`w-3.5 h-3.5 ${isActive ? "text-sky-400" : "text-zinc-400"}`} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Status indicator */}
      <div className="flex items-center gap-3">
        {!isReady ? (
          <div className="flex items-center gap-1.5 text-xs text-amber-400 bg-amber-950/40 px-3 py-1 rounded-full border border-amber-800/60 animate-pulse">
            <AlertTriangle className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">A inicializar servidor (~1 min)...</span>
            <span className="sm:hidden">A ligar...</span>
          </div>
        ) : (
          <div className="flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-950/40 px-2.5 py-1 rounded-full border border-emerald-800/60">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
            <span className="hidden sm:inline">Servidor Operacional</span>
            <span className="sm:hidden">Ativo</span>
          </div>
        )}
      </div>
    </header>
  );
}

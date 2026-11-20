import React, { useEffect, useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { auth } from "@/lib/api";
import { GoldSeal, QrIcon } from "@/components/motifs";

const LINKS = [
    { to: "/verify", en: "Verify", bn: "যাচাই", id: "nav-verify" },
    { to: "/catalogue", en: "Collection", bn: "সংগ্রহ", id: "nav-catalogue" },
    { to: "/register", en: "Loom Desk", bn: "তাঁত-ডেস্ক", id: "nav-register", staff: true },
    { to: "/studio", en: "Voice Studio", bn: "ভয়েস স্টুডিও", id: "nav-studio", staff: true },
];

export default function Navbar() {
    const [user, setUser] = useState(auth.get());
    const navigate = useNavigate();

    useEffect(() => {
        const sync = () => setUser(auth.get());
        window.addEventListener("ts-auth", sync);
        return () => window.removeEventListener("ts-auth", sync);
    }, []);

    const isStaffish = user && (user.role === "staff" || user.role === "admin");

    return (
        <header className="sticky top-0 z-50 glass-cream border-b border-[#d4af37]/40" data-testid="navbar">
            <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3 sm:px-6">
                <Link to="/" className="flex items-center gap-3" data-testid="nav-home-link">
                    <GoldSeal className="h-10 w-10" />
                    <span className="leading-tight">
                        <span className="font-display block text-lg font-bold tracking-wide text-[#4a0d18]">
                            Tant<span className="text-[#b08d2e]">Saakshi</span>
                        </span>
                        <span className="font-bengali block text-[11px] text-[#785c50]">তাঁতসাক্ষী · সুতোর সাক্ষী</span>
                    </span>
                </Link>

                <nav className="ml-auto hidden items-center gap-1 md:flex">
                    {LINKS.filter((l) => !l.staff || isStaffish).map((l) => (
                        <NavLink
                            key={l.to}
                            to={l.to}
                            data-testid={l.id}
                            className={({ isActive }) =>
                                `group rounded-sm px-3.5 py-2 text-sm font-semibold transition-colors ${
                                    isActive ? "bg-[#4a0d18] text-[#f7e9c4]" : "text-[#5e1220] hover:bg-[#d4af37]/20"
                                }`
                            }
                        >
                            <span>{l.en}</span>
                            <span className="font-bengali ml-2 text-xs opacity-70">{l.bn}</span>
                        </NavLink>
                    ))}
                </nav>

                <div className="ml-auto flex items-center gap-2 md:ml-0">
                    {user ? (
                        <div className="flex items-center gap-2" data-testid="nav-user-chip">
                            <span className="hidden text-right sm:block">
                                <span className="block text-xs font-semibold text-[#4a0d18]">{user.name}</span>
                                <span className="block text-[10px] uppercase tracking-widest text-[#b08d2e]">{user.role}</span>
                            </span>
                            <button
                                data-testid="nav-logout-button"
                                onClick={() => {
                                    auth.clear();
                                    navigate("/");
                                }}
                                className="luxe-btn luxe-btn-ghost rounded-sm px-3 py-2 text-xs font-semibold"
                            >
                                Sign out
                            </button>
                        </div>
                    ) : (
                        <Link
                            to="/login"
                            data-testid="nav-login-link"
                            className="luxe-btn rounded-sm px-4 py-2 text-xs font-bold uppercase tracking-widest"
                        >
                            Weaver Login <span className="font-bengali text-[11px] font-normal opacity-80">প্রবেশ</span>
                        </Link>
                    )}
                    <Link to="/verify" className="md:hidden" data-testid="nav-verify-mobile" aria-label="Verify">
                        <QrIcon className="h-6 w-6 text-[#5e1220]" />
                    </Link>
                </div>
            </div>
            <div className="paisley-band opacity-60" />
        </header>
    );
}

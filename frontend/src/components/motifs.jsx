import React from "react";

export const GoldSeal = ({ className = "h-10 w-10" }) => (
    <svg viewBox="0 0 64 64" className={className} fill="none" data-testid="brand-seal">
        <circle cx="32" cy="32" r="30" stroke="#d4af37" strokeWidth="1.6" />
        <circle cx="32" cy="32" r="25" stroke="#d4af37" strokeWidth="0.8" strokeDasharray="2 3" />
        <path
            d="M32 14c4 5 8 8 8 13a8 8 0 1 1-16 0c0-5 4-8 8-13z"
            stroke="#d4af37"
            strokeWidth="1.6"
            fill="rgba(212,175,55,0.16)"
        />
        <path d="M20 46c4-6 8-9 12-9s8 3 12 9" stroke="#d4af37" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M24 40h16M26 44h12" stroke="#d4af37" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
);

export const PaisleyOrnament = ({ className = "h-6 w-auto text-[#d4af37]" }) => (
    <svg viewBox="0 0 120 24" className={className} fill="none" data-testid="paisley-ornament">
        <path d="M2 12h34" stroke="currentColor" strokeWidth="1" strokeDasharray="1 4" strokeLinecap="round" />
        <path d="M118 12H84" stroke="currentColor" strokeWidth="1" strokeDasharray="1 4" strokeLinecap="round" />
        <path
            d="M60 2c6 3 10 6 10 10s-4 10-10 10-10-6-10-10 4-7 10-10z"
            stroke="currentColor"
            strokeWidth="1.4"
        />
        <path d="M60 7c3.4 1.8 5.6 3.4 5.6 5.6S63.4 17 60 17s-5.6-2.2-5.6-4.4S56.6 8.8 60 7z" stroke="currentColor" strokeWidth="1" />
        <circle cx="60" cy="12" r="1.4" fill="currentColor" />
        <path d="M44 12c2-4 6-6 8-6M76 12c-2-4-6-6-8-6" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
);

export const CornerVine = ({ className = "h-16 w-16 text-[#d4af37]", flip = false }) => (
    <svg
        viewBox="0 0 80 80"
        className={`${className} ${flip ? "-scale-x-100" : ""}`}
        fill="none"
        data-testid="corner-vine"
    >
        <path d="M4 76V28C4 14 14 4 28 4h48" stroke="currentColor" strokeWidth="1.4" opacity="0.7" />
        <path d="M12 76V32c0-11 9-20 20-20h44" stroke="currentColor" strokeWidth="0.9" opacity="0.5" />
        <path d="M14 52c10-2 16-10 16-20M30 12c-2 10-10 16-20 16" stroke="currentColor" strokeWidth="1.1" opacity="0.8" />
        <circle cx="30" cy="32" r="2.2" fill="currentColor" opacity="0.9" />
        <circle cx="16" cy="46" r="1.6" fill="currentColor" opacity="0.7" />
        <circle cx="46" cy="16" r="1.6" fill="currentColor" opacity="0.7" />
    </svg>
);

export const MandalaLoader = ({ className = "h-16 w-16 text-[#d4af37]" }) => (
    <svg viewBox="0 0 80 80" className={`mandala-spin ${className}`} fill="none" data-testid="mandala-loader">
        <circle cx="40" cy="40" r="36" stroke="currentColor" strokeWidth="1" strokeDasharray="3 5" />
        <circle cx="40" cy="40" r="26" stroke="currentColor" strokeWidth="1.2" />
        {Array.from({ length: 12 }).map((_, i) => (
            <path
                key={i}
                d="M40 14c3 5 3 9 0 13-3-4-3-8 0-13z"
                stroke="currentColor"
                strokeWidth="1"
                transform={`rotate(${i * 30} 40 40)`}
            />
        ))}
        <circle cx="40" cy="40" r="6" fill="currentColor" opacity="0.6" />
    </svg>
);

export const LoomIcon = ({ className = "h-5 w-5" }) => (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
        <path d="M3 6h18M3 18h18M6 6v12M12 6v12M18 6v12M3 12h18" />
    </svg>
);

export const QrIcon = ({ className = "h-5 w-5" }) => (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.6">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <path d="M14 14h3v3h-3zM20 14v6h-3M17 20h-3v-3" strokeLinecap="round" />
    </svg>
);

export const MicIcon = ({ className = "h-6 w-6" }) => (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
);

export const bn = (n) => {
    const map = { 0: "০", 1: "১", 2: "২", 3: "৩", 4: "৪", 5: "৫", 6: "৬", 7: "৭", 8: "৮", 9: "৯" };
    return String(n).replace(/\d/g, (d) => map[d]);
};

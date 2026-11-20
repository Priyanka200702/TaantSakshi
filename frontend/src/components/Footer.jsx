import React from "react";
import { Link } from "react-router-dom";
import { GoldSeal } from "@/components/motifs";

export default function Footer() {
    return (
        <footer className="maroon-panel paper-grain relative mt-24 text-[#f2e3c8]" data-testid="footer">
            <div className="paisley-band-dark" />
            <div className="mx-auto grid max-w-7xl gap-10 px-6 py-14 md:grid-cols-[1.4fr_1fr_1fr]">
                <div>
                    <div className="flex items-center gap-3">
                        <GoldSeal className="h-11 w-11" />
                        <div>
                            <p className="font-display text-xl font-bold text-[#e9d38a]">
                                Tant<span className="text-[#d4af37]">Saakshi</span>
                            </p>
                            <p className="font-bengali text-xs text-[#cbb490]">তাঁতসাক্ষী — প্রতিটি সুতার সাক্ষী</p>
                        </div>
                    </div>
                    <p className="mt-5 max-w-sm text-sm leading-relaxed text-[#d8c5a4]">
                        A loom-side trust layer for Bengal handloom — thread density measured by physics, identity sealed by
                        digital birth certificates, commerce spoken in the weaver's own voice.
                    </p>
                    <p className="font-bengali mt-3 text-sm text-[#cbb490]">
                        সুতোর ঘনত্ব মাপা হয় বিজ্ঞানে, বিক্রি হয় তাঁতির নিজের ভাষায়।
                    </p>
                </div>
                <div>
                    <p className="eyebrow text-[#d4af37]">Explore</p>
                    <ul className="mt-4 space-y-2.5 text-sm">
                        <li><Link className="hover:text-[#e9d38a]" to="/verify" data-testid="footer-verify-link">Verify a saree</Link></li>
                        <li><Link className="hover:text-[#e9d38a]" to="/catalogue" data-testid="footer-catalogue-link">Verified collection</Link></li>
                        <li><Link className="hover:text-[#e9d38a]" to="/register" data-testid="footer-register-link">Loom-side register</Link></li>
                        <li><Link className="hover:text-[#e9d38a]" to="/studio" data-testid="footer-studio-link">Bengali voice studio</Link></li>
                    </ul>
                </div>
                <div>
                    <p className="eyebrow text-[#d4af37]">Crafts we seal</p>
                    <ul className="mt-4 space-y-2.5 text-sm text-[#d8c5a4]">
                        <li>Dhaniakhali Tant</li>
                        <li>Santipur Jamdani</li>
                        <li>Bishnupur Baluchari</li>
                        <li>Bolpur Kantha</li>
                    </ul>
                </div>
            </div>
            <div className="gold-rule" />
            <div className="flex flex-col items-center justify-between gap-2 px-6 py-5 text-[11px] uppercase tracking-[0.3em] text-[#a98f68] sm:flex-row">
                <span>TantSaakshi Heritage Trust Layer</span>
                <span>Handwoven in Bengal · ভারত · পশ্চিমবঙ্গ</span>
            </div>
        </footer>
    );
}

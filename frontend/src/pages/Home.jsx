import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { CornerVine, GoldSeal, LoomIcon, MicIcon, PaisleyOrnament, QrIcon, bn } from "@/components/motifs";

const IMG = {
    heroSide: "https://images.unsplash.com/photo-1661621968475-f08ec1a768fc?crop=entropy&cs=srgb&fm=jpg&q=85",
    loomMacro: "https://images.unsplash.com/photo-1707978932202-751b08324daf?crop=entropy&cs=srgb&fm=jpg&q=85",
    weaver: "https://images.pexels.com/photos/32673642/pexels-photo-32673642.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
    sareeDetail: "https://images.unsplash.com/photo-1588140686379-1b76a52103dc?crop=entropy&cs=srgb&fm=jpg&q=85",
    textiles: "https://images.unsplash.com/photo-1569909115134-a0426936c879?crop=entropy&cs=srgb&fm=jpg&q=85",
    jamdani: "https://images.unsplash.com/photo-1638310533874-6c124c012e1d?crop=entropy&cs=srgb&fm=jpg&q=85",
    threads: "https://images.unsplash.com/photo-1599303000936-1cf21eac4456?crop=entropy&cs=srgb&fm=jpg&q=85",
    artisan: "https://images.pexels.com/photos/14953193/pexels-photo-14953193.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
};

const Pillar = ({ num, icon, title, bnTitle, text, bnText, to, cta, testid }) => (
    <Link
        to={to}
        data-testid={testid}
        className="paper-grain group relative overflow-hidden rounded-sm border border-[#d4af37]/45 bg-white p-7 shadow-[0_24px_50px_-30px_rgba(58,10,19,0.45)] transition-all duration-300 hover:-translate-y-1.5 hover:shadow-[0_34px_60px_-28px_rgba(58,10,19,0.55)]"
    >
        <CornerVine className="absolute right-0 top-0 h-12 w-12 text-[#d4af37]/70" flip />
        <span className="font-display absolute -bottom-5 -right-2 text-[92px] font-black leading-none text-[#f4e8d0]">{num}</span>
        <div className="relative">
            <div className="maroon-panel inline-flex h-12 w-12 items-center justify-center rounded-full border border-[#d4af37]/70 text-[#e9d38a]">
                {icon}
            </div>
            <h3 className="font-display mt-4 text-xl font-bold text-[#4a0d18]">{title}</h3>
            <p className="font-bengali text-xs text-[#b08d2e]">{bnTitle}</p>
            <p className="mt-3 text-sm leading-relaxed text-[#5e4936]">{text}</p>
            <p className="font-bengali mt-1.5 text-xs leading-relaxed text-[#8a715c]">{bnText}</p>
            <span className="mt-4 inline-block text-xs font-bold uppercase tracking-[0.25em] text-[#8b263e] transition-all group-hover:tracking-[0.35em]">
                {cta} →
            </span>
        </div>
    </Link>
);

const CRAFTS = [
    { name: "Dhaniakhali Tant", bn: "ধানীয়াখালি তাঁত", note: "Crisp cotton, candy borders", img: IMG.textiles },
    { name: "Santipur Jamdani", bn: "শান্তিপুর জামদানি", note: "Floating buti, breathable muslin", img: IMG.jamdani },
    { name: "Bishnupur Baluchari", bn: "বিষ্ণুপুর বালুচরি", note: "Mythological pallu scenes", img: IMG.artisan },
    { name: "Bolpur Kantha", bn: "বোলপুর কাঁথা", note: "Thousand-stitch embroidery", img: IMG.sareeDetail },
];

export default function Home() {
    const [stats, setStats] = useState(null);

    useEffect(() => {
        api.get("/listings").then((r) => setStats(r.data.listings)).catch(() => setStats([]));
    }, []);

    const verified = stats ? stats.length : null;

    return (
        <main data-testid="home-page">
            {/* ================= HERO ================= */}
            <section className="maroon-panel paper-grain relative overflow-hidden text-[#f2e3c8]">
                <div className="temple-edge" />
                <CornerVine className="absolute left-0 top-0 z-10 h-24 w-24 text-[#d4af37]" />
                <CornerVine className="absolute bottom-6 left-0 z-10 h-24 w-24 text-[#d4af37] -scale-y-100" />
                <div className="mx-auto grid max-w-7xl items-center gap-12 px-6 py-16 sm:py-20 lg:grid-cols-[1.15fr_1fr] lg:py-24">
                    <div>
                        <p className="fade-up eyebrow text-[#e9d38a]">Bengal Handloom · <span className="font-bengali normal-case tracking-normal">বাংলার তাঁত</span></p>
                        <h1 className="fade-up d1 font-display mt-5 text-4xl font-black leading-[1.05] sm:text-5xl lg:text-6xl">
                            Every thread
                            <br />
                            bears <span className="gold-text italic">witness.</span>
                        </h1>
                        <p className="font-bengali fade-up d2 mt-4 text-lg text-[#e9d38a]">প্রতিটি সুতো সাক্ষী দেয়।</p>
                        <p className="fade-up d2 mt-5 max-w-lg text-base leading-relaxed text-[#d8c5a4]">
                            TantSaakshi is the loom-side trust layer for Bengal handloom — thread density measured by 2D-FFT
                            physics at the cooperative, sealed as a digital birth certificate, and sold in the weaver's own
                            voice.
                        </p>
                        <div className="fade-up d3 mt-8 flex flex-wrap gap-4">
                            <Link to="/verify" data-testid="hero-verify-cta" className="luxe-btn luxe-btn-gold rounded-sm px-7 py-3.5 text-sm font-bold uppercase tracking-[0.2em]">
                                <QrIcon className="h-4 w-4" /> Verify a saree <span className="font-bengali text-xs font-normal opacity-80">যাচাই করুন</span>
                            </Link>
                            <Link to="/catalogue" data-testid="hero-catalogue-cta" className="luxe-btn luxe-btn-ghost rounded-sm px-7 py-3.5 text-sm font-bold uppercase tracking-[0.2em]">
                                The Collection <span className="font-bengali text-xs font-normal opacity-80">সংগ্রহ</span>
                            </Link>
                        </div>
                        <div className="fade-up d4 mt-10 flex flex-wrap gap-8">
                            {[
                                { v: verified == null ? "·" : String(verified), en: "Verified masterpieces", b: "যাচাইকৃত শাড়ি" },
                                { v: "২", en: "Weaving cooperatives", b: "সমবায় সমিতি" },
                                { v: "৬০–১০০", en: "EPI measured, physics-honest", b: "সুতো/ইঞ্চি মাপা" },
                            ].map((s) => (
                                <div key={s.en} data-testid="hero-stat">
                                    <p className="font-display text-3xl font-bold text-[#e9d38a]">{s.v}</p>
                                    <p className="text-[11px] uppercase tracking-[0.18em] text-[#cbb490]">{s.en}</p>
                                    <p className="font-bengali text-[11px] text-[#a98f68]">{s.b}</p>
                                </div>
                            ))}
                        </div>
                    </div>

                    <div className="fade-up d2 relative">
                        <div className="gold-frame relative rounded-sm">
                            <img src={IMG.weaver} alt="Master weaver at a Bengal pit loom" className="h-[440px] w-full rounded-sm object-cover sm:h-[520px]" data-testid="hero-image" />
                            <div className="shimmer absolute inset-0 rounded-sm" />
                        </div>
                        <div className="glass-cream absolute -left-4 top-8 rounded-sm border border-[#d4af37]/60 px-4 py-3 shadow-xl sm:-left-8" data-testid="hero-chip-epi">
                            <p className="font-display text-xl font-bold text-[#5e1220]">EPI 60.0</p>
                            <p className="text-[10px] uppercase tracking-[0.2em] text-[#785c50]">Ends / inch · FFT-measured</p>
                        </div>
                        <div className="glass-cream absolute -right-3 bottom-10 flex items-center gap-2 rounded-sm border border-[#d4af37]/60 px-4 py-3 shadow-xl sm:-right-6" data-testid="hero-chip-verified">
                            <GoldSeal className="h-8 w-8" />
                            <div>
                                <p className="text-xs font-bold uppercase tracking-[0.18em] text-[#5e1220]">Weave verified</p>
                                <p className="font-bengali text-[10px] text-[#785c50]">জন্ম সনদ ইস্যুকৃত</p>
                            </div>
                        </div>
                    </div>
                </div>
                <div className="paisley-band opacity-80" />
            </section>

            {/* ================= PILLARS ================= */}
            <section className="mx-auto max-w-7xl px-6 py-20">
                <div className="text-center">
                    <p className="eyebrow text-[#b08d2e]">The Saakshi Way</p>
                    <h2 className="font-display mt-3 text-3xl font-bold text-[#4a0d18] sm:text-4xl">Three vows at the loom</h2>
                    <p className="font-bengali mt-2 text-[#785c50]">তিনটি প্রতিজ্ঞা — নিবন্ধন, যাচাই, বিক্রয়</p>
                    <PaisleyOrnament className="mx-auto mt-5 h-6 w-44 text-[#d4af37]" />
                </div>
                <div className="mt-12 grid gap-7 md:grid-cols-3">
                    <Pillar
                        num="১"
                        testid="pillar-register"
                        icon={<LoomIcon className="h-5 w-5" />}
                        title="Register"
                        bnTitle="নিবন্ধন"
                        text="At the cooperative loom, the saree poses inside a standardized optical jig. A phone burst feeds our 2D-FFT engine — EPI, PPI, irregularity and a micro-texture fingerprint no copy can fake."
                        bnText="অপটিক্যাল জিগে তোলা ছবি থেকে FFT ইঞ্জিন সুতোর ঘনত্ব মেপে ফিঙ্গারপ্রিন্ট তৈরি করে।"
                        to="/register"
                        cta="Enter the loom desk"
                    />
                    <Pillar
                        num="২"
                        testid="pillar-verify"
                        icon={<QrIcon className="h-5 w-5" />}
                        title="Verify"
                        bnTitle="যাচাই"
                        text="Each weave receives a tamper-proof digital birth certificate bound to its physical gold QR tag. Buyers inspect macro weave structure and cooperative provenance on any phone, instantly."
                        bnText="QR স্ক্যান করলেই ক্রেতা দেখতে পান জন্ম সনদ, বুননের গঠন ও সমবায়ের উৎস।"
                        to="/verify"
                        cta="Inspect a certificate"
                    />
                    <Pillar
                        num="৩"
                        testid="pillar-sell"
                        icon={<MicIcon className="h-5 w-5" />}
                        title="Sell"
                        bnTitle="বিক্রয়"
                        text="Zero typing. The weaver speaks in Bengali; Whisper AI transcribes and AI pens the listing. One tap publishes to the catalogue, WhatsApp Business and an ONDC-ready feed."
                        bnText="তাঁতি বাংলায় বলেন, AI লেখে — এক টোকায় WhatsApp ও ONDC-তে প্রকাশ।"
                        to="/studio"
                        cta="Open the voice studio"
                    />
                </div>
            </section>

            {/* ================= TRUST TIMELINE ================= */}
            <section className="weave-panel border-y border-[#d4af37]/40 py-20">
                <div className="mx-auto max-w-7xl px-6">
                    <div className="text-center">
                        <p className="eyebrow text-[#b08d2e]">How trust is woven</p>
                        <h2 className="font-display mt-3 text-3xl font-bold text-[#4a0d18]">From loom to palm, four steps</h2>
                    </div>
                    <div className="mt-12 grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
                        {[
                            { n: "১", t: "Pose in the jig", b: "জিগে শাড়ি বসান", d: "The optical jig fixes distance, light and angle — every saree photographed the same honest way." },
                            { n: "২", t: "Physics counts threads", b: "FFT সুতো গোনে", d: "2D FFT turns the weave into a spectrum; peaks become ends and picks per inch. No guessing, no promises." },
                            { n: "৩", t: "Birth certificate seals it", b: "জন্ম সনদ তৈরি", d: "EPI/PPI, grade and micro-texture fingerprint are sealed to the gold QR tag — tamper-proof by design." },
                            { n: "৪", t: "Buyer verifies in seconds", b: "ক্রেতা যাচাই করেন", d: "One scan on the saraya shows the weave, the cooperative, and the weaver's own voice-told story." },
                        ].map((s, i) => (
                            <div key={s.t} className="relative" data-testid={`trust-step-${i + 1}`}>
                                <span className="maroon-panel font-display inline-flex h-14 w-14 items-center justify-center rounded-full border border-[#d4af37]/70 text-2xl font-bold text-[#e9d38a]">
                                    {s.n}
                                </span>
                                <h3 className="font-display mt-4 text-lg font-bold text-[#4a0d18]">{s.t}</h3>
                                <p className="font-bengali text-xs text-[#b08d2e]">{s.b}</p>
                                <p className="mt-2 text-sm leading-relaxed text-[#5e4936]">{s.d}</p>
                            </div>
                        ))}
                    </div>
                </div>
            </section>

            {/* ================= CRAFT GALLERY ================= */}
            <section className="mx-auto max-w-7xl px-6 py-20">
                <div className="flex flex-wrap items-end justify-between gap-4">
                    <div>
                        <p className="eyebrow text-[#b08d2e]">Living crafts</p>
                        <h2 className="font-display mt-3 text-3xl font-bold text-[#4a0d18] sm:text-4xl">Each weave, a district's signature</h2>
                        <p className="font-bengali mt-2 text-[#785c50]">প্রতিটি বুনন এক জেলার স্বাক্ষর</p>
                    </div>
                    <Link to="/catalogue" data-testid="crafts-view-all" className="luxe-btn luxe-btn-ghost rounded-sm px-5 py-2.5 text-xs font-bold uppercase tracking-[0.2em]">
                        View all
                    </Link>
                </div>
                <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
                    {CRAFTS.map((c, i) => (
                        <div key={c.name} className={`fade-up d${i + 1} group relative overflow-hidden rounded-sm`} data-testid={`craft-card-${i + 1}`}>
                            <img src={c.img} alt={c.name} className="h-72 w-full object-cover transition-transform duration-700 group-hover:scale-110" />
                            <div className="absolute inset-0 bg-gradient-to-t from-[#3a0a13]/90 via-[#3a0a13]/20 to-transparent" />
                            <div className="absolute bottom-0 left-0 right-0 p-4 text-[#f2e3c8]">
                                <h3 className="font-display text-lg font-bold">{c.name}</h3>
                                <p className="font-bengali text-xs text-[#e9d38a]">{c.bn}</p>
                                <p className="mt-1 text-xs text-[#d8c5a4]">{c.note}</p>
                            </div>
                        </div>
                    ))}
                </div>
            </section>

            {/* ================= VOICE BAND ================= */}
            <section className="maroon-panel relative overflow-hidden py-16 text-center text-[#f2e3c8]">
                <div className="paisley-band-dark absolute top-0 left-0 right-0 opacity-60" />
                <MicIcon className="mx-auto h-10 w-10 text-[#e9d38a]" />
                <h2 className="font-display mx-auto mt-4 max-w-3xl px-6 text-3xl font-bold sm:text-4xl">
                    “বললেই হল — <span className="gold-text italic">just speak, it sells.</span>”
                </h2>
                <p className="mx-auto mt-4 max-w-xl px-6 text-sm leading-relaxed text-[#d8c5a4]">
                    Most master weavers never typed a listing in their lives. In TantSaakshi's studio they describe the saree in
                    Bengali — the craft, the aanchal, the occasion — and AI writes the listing, publishes it, and carries it to
                    WhatsApp and ONDC.
                </p>
                <Link to="/studio" data-testid="voice-band-cta" className="luxe-btn luxe-btn-gold mt-7 rounded-sm px-7 py-3 text-xs font-bold uppercase tracking-[0.25em]">
                    Hear the loom speak
                </Link>
            </section>

            {/* ================= FINAL CTA ================= */}
            <section className="mx-auto max-w-3xl px-6 py-20 text-center">
                <GoldSeal className="mx-auto h-16 w-16" />
                <h2 className="font-display mt-5 text-3xl font-bold text-[#4a0d18] sm:text-4xl">Hold the truth in your hands</h2>
                <p className="font-bengali mt-2 text-[#785c50]">সত্য এখন হাতের মুঠোয়</p>
                <p className="mt-4 text-sm leading-relaxed text-[#5e4936]">
                    If a saree cannot show its birth certificate, it cannot call itself handloom. Ask for the gold tag — or scan
                    one right now.
                </p>
                <div className="mt-7 flex flex-wrap justify-center gap-4">
                    <Link to="/verify" data-testid="final-verify-cta" className="luxe-btn rounded-sm px-8 py-3.5 text-sm font-bold uppercase tracking-[0.2em]">
                        Verify now
                    </Link>
                    <Link to="/catalogue" data-testid="final-catalogue-cta" className="luxe-btn luxe-btn-ghost rounded-sm px-8 py-3.5 text-sm font-bold uppercase tracking-[0.2em]">
                        Meet the weavers
                    </Link>
                </div>
            </section>
        </main>
    );
}

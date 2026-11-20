import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, photoUrl } from "@/lib/api";
import { PaisleyOrnament } from "@/components/motifs";

const money = (p) => (p ? `₹${p.toLocaleString("en-IN")}` : "Price on request");

const CRAFT_IMAGERY = {
    Tant: "https://images.unsplash.com/photo-1569909115134-a0426936c879?crop=entropy&cs=srgb&fm=jpg&q=85",
    Jamdani: "https://images.unsplash.com/photo-1638310533874-6c124c012e1d?crop=entropy&cs=srgb&fm=jpg&q=85",
    Baluchari: "https://images.pexels.com/photos/14953193/pexels-photo-14953193.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
    Kantha: "https://images.unsplash.com/photo-1588140686379-1b76a52103dc?crop=entropy&cs=srgb&fm=jpg&q=85",
};
const craftImage = (item) => CRAFT_IMAGERY[item.saree_type] || photoUrl(item.photo_url);

function Detail({ item, onClose }) {
    return (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#3a0a13]/90 p-4" onClick={onClose} data-testid="catalogue-detail-modal">
            <div className="paper-grain max-h-[88vh] w-full max-w-3xl overflow-y-auto rounded-sm bg-white" onClick={(e) => e.stopPropagation()}>
                <div className="grid md:grid-cols-2">
                    <img src={craftImage(item)} alt={item.listing?.title || item.saree_type} className="h-72 w-full object-cover md:h-full" />
                    <div className="p-7">
                        <p className="eyebrow text-[#b08d2e]">{item.saree_type}</p>
                        <h2 className="font-display mt-2 text-2xl font-bold text-[#4a0d18]">{item.listing?.title || "Handloom Saree"}</h2>
                        <p className="font-bengali text-sm text-[#785c50]">{item.listing?.story_bn || "গল্পটি শীঘ্রই আসছে"}</p>
                        <p className="mt-3 text-sm leading-relaxed text-[#5e4936]">{item.listing?.story_en || "This weave is thread-verified; the weaver's story is on its way."}</p>
                        <p className="font-display mt-4 text-2xl font-bold text-[#8b263e]">{money(item.listing?.price_inr)}</p>
                        <dl className="mt-4 space-y-1.5 text-sm text-[#5e4936]">
                            <div className="flex justify-between border-b border-[#d4af37]/25 pb-1.5"><dt>Ends / inch</dt><dd className="tabular font-semibold">{item.ends_per_inch?.toFixed(1)}</dd></div>
                            <div className="flex justify-between border-b border-[#d4af37]/25 pb-1.5"><dt>Picks / inch</dt><dd className="tabular font-semibold">{item.picks_per_inch?.toFixed(1)}</dd></div>
                            <div className="flex justify-between border-b border-[#d4af37]/25 pb-1.5"><dt>Cooperative</dt><dd className="text-right">{item.cooperative}</dd></div>
                            <div className="flex justify-between border-b border-[#d4af37]/25 pb-1.5"><dt>District</dt><dd>{item.district}</dd></div>
                            <div className="flex justify-between"><dt>Master weaver</dt><dd>{item.weaver || "Honoured anonymously"}</dd></div>
                        </dl>
                        <a href={`/c/${item.qr_id}`} data-testid="detail-certificate-link" className="luxe-btn mt-6 justify-center rounded-sm px-6 py-3 text-xs font-bold uppercase tracking-[0.2em]">
                            Open birth certificate
                        </a>
                    </div>
                </div>
            </div>
        </div>
    );
}

export default function Catalogue() {
    const [items, setItems] = useState(null);
    const [craft, setCraft] = useState("All");
    const [open, setOpen] = useState(null);

    useEffect(() => {
        api.get("/listings").then((r) => setItems(r.data.listings)).catch(() => setItems([]));
    }, []);

    const crafts = useMemo(() => ["All", ...new Set((items || []).map((i) => i.saree_type))], [items]);
    const shown = (items || []).filter((i) => craft === "All" || i.saree_type === craft);

    return (
        <main className="mx-auto max-w-7xl px-6 py-14" data-testid="catalogue-page">
            <div className="text-center">
                <p className="eyebrow text-[#b08d2e]">Verified collection</p>
                <h1 className="font-display mt-3 text-3xl font-bold text-[#4a0d18] sm:text-4xl">Masterworks with a witness</h1>
                <p className="font-bengali mt-2 text-[#785c50]">যাচাইকৃত সংগ্রহ — প্রতিটি শাড়ির জন্ম সনদ আছে</p>
                <PaisleyOrnament className="mx-auto mt-4 h-6 w-44 text-[#d4af37]" />
            </div>

            <div className="mt-8 flex flex-wrap justify-center gap-2" data-testid="catalogue-filters">
                {crafts.map((c) => (
                    <button
                        key={c}
                        data-testid={`catalogue-filter-${c.toLowerCase().replace(/\s+/g, "-")}`}
                        onClick={() => setCraft(c)}
                        className={`rounded-full border px-4 py-1.5 text-xs font-semibold tracking-wide transition-colors ${
                            craft === c ? "border-[#4a0d18] bg-[#4a0d18] text-[#e9d38a]" : "border-[#d4af37]/60 bg-white text-[#5e1220] hover:bg-[#fff7ee]"
                        }`}
                    >
                        {c}
                    </button>
                ))}
            </div>

            {items === null ? (
                <p className="py-20 text-center text-sm uppercase tracking-[0.3em] text-[#a08a6e]">Unfolding the collection…</p>
            ) : (
                <div className="mt-10 grid gap-7 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                    {shown.map((item) => (
                        <article
                            key={item.qr_id}
                            data-testid={`catalogue-card-${item.qr_id}`}
                            className="paper-grain group cursor-pointer overflow-hidden rounded-sm border border-[#d4af37]/45 bg-white shadow-[0_20px_44px_-26px_rgba(58,10,19,0.45)] transition-all duration-300 hover:-translate-y-1.5"
                            onClick={() => setOpen(item)}
                        >
                            <div className="relative overflow-hidden">
                                <img src={craftImage(item)} alt={item.listing?.title || item.saree_type} className="h-64 w-full object-cover transition-transform duration-700 group-hover:scale-110" />
                                <span className="absolute left-3 top-3 rounded-full bg-[#4a0d18]/90 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-[#e9d38a]">
                                    {item.tag_status === "listed" ? "Verified · Listed" : "Verified"}
                                </span>
                                {item.grade ? (
                                    <span className="absolute right-3 top-3 flex h-9 w-9 items-center justify-center rounded-full border border-[#d4af37] bg-[#fff7ee] font-display text-sm font-black text-[#5e1220]">
                                        {item.grade}
                                    </span>
                                ) : null}
                            </div>
                            <div className="p-5">
                                <h3 className="font-display truncate text-lg font-bold text-[#4a0d18]">{item.listing?.title || `Handloom ${item.saree_type}`}</h3>
                                <p className="font-bengali truncate text-xs text-[#b08d2e]">{item.saree_type} · {item.district}</p>
                                <div className="mt-3 flex items-center justify-between">
                                    <span className="font-display text-lg font-bold text-[#8b263e]">{money(item.listing?.price_inr)}</span>
                                    <span className="tabular rounded-sm border border-[#d4af37]/50 bg-[#fff7ee] px-2 py-1 font-mono text-[10px] tracking-wider text-[#785c50]">
                                        {item.ends_per_inch?.toFixed(0)}×{item.picks_per_inch?.toFixed(0)} /in
                                    </span>
                                </div>
                                <p className="mt-2 truncate text-xs text-[#785c50]">
                                    {item.cooperative}{item.weaver ? ` · ${item.weaver}` : ""}
                                </p>
                            </div>
                        </article>
                    ))}
                </div>
            )}

            {items !== null && shown.length === 0 ? (
                <div className="mx-auto mt-10 max-w-lg rounded-sm border border-dashed border-[#d4af37]/60 bg-white/60 p-10 text-center text-sm text-[#785c50]" data-testid="catalogue-empty">
                    No verified sarees in this craft yet — the looms are still at work.
                    <span className="font-bengali mt-2 block">এই কারুকাজে এখনও কোনো যাচাইকৃত শাড়ি নেই।</span>
                </div>
            ) : null}

            {open ? <Detail item={open} onClose={() => setOpen(null)} /> : null}
        </main>
    );
}

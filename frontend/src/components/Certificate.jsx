import React, { useState } from "react";
import { QRCodeCanvas } from "qrcode.react";
import { CornerVine, GoldSeal, MandalaLoader, PaisleyOrnament } from "@/components/motifs";
import { photoUrl } from "@/lib/api";

const Kv = ({ en, bnLabel, value, testid }) => (
    <div className="flex items-baseline justify-between gap-4 border-b border-[#d4af37]/25 py-2.5" data-testid={testid}>
        <span className="text-[11px] uppercase tracking-[0.2em] text-[#785c50]">
            {en} <span className="font-bengali normal-case tracking-normal text-[#a08a6e]">· {bnLabel}</span>
        </span>
        <span className="text-right text-sm font-semibold text-[#4a0d18]">{value || "—"}</span>
    </div>
);

const Metric = ({ label, bnLabel, value, testid }) => (
    <div className="weave-panel rounded-sm border border-[#d4af37]/40 px-4 py-3 text-center" data-testid={testid}>
        <p className="tabular font-display text-3xl font-bold text-[#5e1220]">{value ?? "·"}</p>
        <p className="mt-1 text-[10px] uppercase tracking-[0.22em] text-[#785c50]">
            {label} <span className="font-bengali normal-case tracking-normal">· {bnLabel}</span>
        </p>
    </div>
);

function StateShell({ title, bnTitle, children, tone = "calm" }) {
    return (
        <div className="paper-grain relative mx-auto max-w-2xl rounded-sm border border-[#d4af37]/50 bg-white p-10 text-center shadow-[0_30px_60px_-30px_rgba(58,10,19,0.4)]">
            <CornerVine className="absolute left-0 top-0 h-14 w-14 text-[#d4af37]" />
            <CornerVine className="absolute right-0 top-0 h-14 w-14 text-[#d4af37]" flip />
            <CornerVine className="absolute bottom-0 left-0 h-14 w-14 text-[#d4af37] -scale-y-100" />
            <CornerVine className="absolute bottom-0 right-0 h-14 w-14 text-[#d4af37] -scale-y-100 -scale-x-100" />
            <div className="relative">
                <GoldSeal className={`mx-auto h-14 w-14 ${tone === "alert" ? "opacity-60" : ""}`} />
                <h3 className="font-display mt-4 text-2xl font-bold text-[#4a0d18]">{title}</h3>
                <p className="font-bengali text-sm text-[#785c50]">{bnTitle}</p>
                <div className="mt-4 text-sm leading-relaxed text-[#5e4936]">{children}</div>
            </div>
        </div>
    );
}

export default function Certificate({ data }) {
    const [zoom, setZoom] = useState(false);
    if (!data) return null;

    if (data.state === "unknown")
        return (
            <div data-testid="certificate-panel" data-cert-state="unknown">
                <StateShell title="Not a TantSaakshi tag" bnTitle="এটি একটি বৈধ তাঁতসাক্ষী ট্যাগ নয়" tone="alert">
                    No birth certificate exists for <span className="font-mono font-semibold">{data.qr_id}</span>. Genuine tags
                    carry a gold seal QR printed at the cooperative. বৈধ ট্যাগে সোনালি সিল-QR থাকে।
                </StateShell>
            </div>
        );

    if (data.state === "blank")
        return (
            <div data-testid="certificate-panel" data-cert-state="blank">
                <StateShell title="A genuine tag, awaiting its saree" bnTitle="বৈধ ট্যাগ, শাড়ির অপেক্ষায়">
                    <p>
                        Issued by <b>{data.cooperative?.name || "the cooperative"}</b> ({data.cooperative?.district}). This tag
                        has not been woven-registered yet — no certificate can be claimed on it.
                    </p>
                    <p className="font-bengali mt-2">এই ট্যাগে এখনও কোনো শাড়ি নিবন্ধিত হয়নি।</p>
                </StateShell>
            </div>
        );

    if (data.state === "processing")
        return (
            <div data-testid="certificate-panel" data-cert-state="processing">
                <StateShell title="Threads are being counted" bnTitle="সুতো গণনা চলছে">
                    <MandalaLoader className="mx-auto my-3 h-16 w-16 text-[#b08d2e]" />
                    <p>The loom-side engine is measuring this saree's weave right now. Its certificate will appear here.</p>
                    <p className="font-bengali">ইঞ্জিন এখন বুনন মাপছে, সামান্য অপেক্ষা করুন।</p>
                </StateShell>
            </div>
        );

    if (data.state === "failed")
        return (
            <div data-testid="certificate-panel" data-cert-state="failed">
                <StateShell title="Registration did not pass quality" bnTitle="নিবন্ধন গুণমান পরীক্ষায় ব্যর্থ" tone="alert">
                    {data.reason || "The photograph burst failed the optical quality gates."}
                    {data.reason ? <p className="font-bengali mt-1">{data.reason}</p> : null}
                    <p className="mt-3 text-xs text-[#a08a6e]">The tag is released for a fresh registration — nothing fake is ever issued.</p>
                </StateShell>
            </div>
        );

    const d = data;
    return (
        <div data-testid="certificate-panel" data-cert-state="verified" className="mx-auto max-w-4xl">
            {d.warning_repeated_scan ? (
                <div
                    data-testid="cert-scan-warning"
                    className="mb-4 flex items-start gap-3 rounded-sm border border-amber-500/60 bg-amber-50 px-4 py-3 text-sm text-amber-900"
                >
                    <span className="mt-0.5 text-lg">⚠</span>
                    <span>
                        This tag has been scanned unusually often (or is marked sold). Insist on verifying the physical weave.
                        <span className="font-bengali block text-xs">এই ট্যাগ অস্বাভাবিক বেশিবার স্ক্যান হয়েছে — সতর্ক হোন।</span>
                    </span>
                </div>
            ) : null}

            <div className="paper-grain relative overflow-hidden rounded-sm bg-white shadow-[0_40px_80px_-40px_rgba(58,10,19,0.5)]">
                <div className="maroon-panel relative px-6 py-5 text-center sm:px-10">
                    <div className="paisley-band-dark absolute bottom-0 left-0 right-0 opacity-70" />
                    <p className="eyebrow text-[#e9d38a]">TantSaakshi Digital Birth Certificate</p>
                    <p className="font-bengali mt-1 text-sm text-[#d8c5a4]">তাঁতসাক্ষী জন্ম সনদ</p>
                    <p className="mt-2 inline-block rounded-sm border border-[#d4af37]/50 px-3 py-1 font-mono text-xs tracking-[0.3em] text-[#e9d38a]" data-testid="cert-qr-id">
                        {d.qr_id}
                    </p>
                </div>

                <div className="grid gap-8 p-6 sm:p-10 md:grid-cols-[1fr_1.2fr]">
                    <div>
                        <button
                            type="button"
                            onClick={() => setZoom(true)}
                            className="gold-frame block w-full overflow-hidden rounded-sm bg-[#fff7ee]"
                            data-testid="cert-photo"
                        >
                            <img
                                src={photoUrl(d.photo_url)}
                                alt={`${d.saree_type} registered weave`}
                                className="h-64 w-full object-cover transition-transform duration-500 hover:scale-105"
                            />
                        </button>
                        <p className="mt-2 text-center text-[10px] uppercase tracking-[0.25em] text-[#a08a6e]">
                            Registered macro weave · নিবন্ধিত বুনন
                        </p>

                        <div className="mt-6 flex flex-col items-center gap-2" data-testid="cert-qr-block">
                            <div className="rounded-sm border border-[#d4af37]/60 bg-white p-2">
                                <QRCodeCanvas value={d.certificate_url || d.qr_id} size={92} fgColor="#4a0d18" />
                            </div>
                            <p className="text-[10px] uppercase tracking-[0.22em] text-[#785c50]">Scan anytime · যেকোনো সময় স্ক্যান</p>
                        </div>
                    </div>

                    <div>
                        <div className="grid grid-cols-3 gap-3">
                            <Metric label="Ends / inch" bnLabel="বুনন ঘনত্ব" value={d.ends_per_inch ? d.ends_per_inch.toFixed(1) : null} testid="cert-epi" />
                            <Metric label="Picks / inch" bnLabel="কুলু ঘনত্ব" value={d.picks_per_inch ? d.picks_per_inch.toFixed(1) : null} testid="cert-ppi" />
                            <div className="maroon-panel flex flex-col items-center justify-center rounded-sm border border-[#d4af37]/50 px-2 py-3" data-testid="cert-grade">
                                <p className="font-display text-3xl font-bold text-[#e9d38a]">{d.grade || "P"}</p>
                                <p className="text-[9px] uppercase tracking-[0.2em] text-[#d8c5a4]">{d.grade ? "Grade" : "Provisional"}</p>
                            </div>
                        </div>

                        <div className="mt-4">
                            <Kv en="Craft" bnLabel="কারুকাজ" value={d.saree_type} testid="cert-craft" />
                            <Kv en="Cooperative" bnLabel="সমবায়" value={d.cooperative?.name} testid="cert-coop" />
                            <Kv en="District" bnLabel="জেলা" value={d.cooperative?.district} testid="cert-district" />
                            <Kv en="Master weaver" bnLabel="তাঁতি" value={d.weaver || "Honoured anonymously"} testid="cert-weaver" />
                            <Kv en="Woven & registered" bnLabel="নিবন্ধন তারিখ" value={d.registered_at} testid="cert-date" />
                            {d.irregularity ? (
                                <Kv
                                    en="Weave regularity"
                                    bnLabel="নিয়মিত বুনন"
                                    value={`${((1 - Math.min(1, (d.irregularity.warp + d.irregularity.weft) / 2)) * 100).toFixed(1)}%`}
                                    testid="cert-regularity"
                                />
                            ) : null}
                        </div>

                        {d.listing ? (
                            <div className="weave-panel mt-5 rounded-sm border border-[#d4af37]/40 p-4" data-testid="cert-story">
                                <p className="font-cormorant text-lg font-semibold italic text-[#5e1220]">“{d.listing.title}”</p>
                                {d.listing.story_en ? <p className="mt-1 text-sm leading-relaxed text-[#5e4936]">{d.listing.story_en}</p> : null}
                                {d.listing.story_bn ? <p className="font-bengali mt-2 text-sm leading-relaxed text-[#785c50]">{d.listing.story_bn}</p> : null}
                            </div>
                        ) : null}
                    </div>
                </div>

                <div className="border-t border-[#d4af37]/40 bg-[#fff7ee] px-6 py-4 sm:px-10">
                    <div className="flex flex-col items-center justify-between gap-2 text-[11px] uppercase tracking-[0.2em] text-[#785c50] sm:flex-row">
                        <span className="flex items-center gap-2">
                            <GoldSeal className="h-5 w-5" /> Measured by 2D FFT physics · পদার্থবিজ্ঞানে মাপা
                        </span>
                        <span className="font-mono normal-case tracking-widest">{d.certificate_url?.replace(/^https?:\/\//, "")}</span>
                    </div>
                </div>
            </div>

            {zoom ? (
                <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#3a0a13]/90 p-4" onClick={() => setZoom(false)} data-testid="cert-photo-modal">
                    <img src={photoUrl(d.photo_url)} alt="Registered weave, full view" className="gold-frame max-h-[85vh] rounded-sm object-contain" />
                </div>
            ) : null}
        </div>
    );
}

export { PaisleyOrnament };

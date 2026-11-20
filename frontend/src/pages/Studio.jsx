import React, { useContext, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, isStaff, photoUrl } from "@/lib/api";
import { useAuth } from "@/pages/Login";
import { CornerVine, GoldSeal, MandalaLoader, MicIcon, PaisleyOrnament } from "@/components/motifs";

const PROMPTS = [
    { en: "The saree's name", bn: "শাড়ির নাম" },
    { en: "The craft & your district", bn: "কারুকাজ ও জেলা" },
    { en: "Colour, motif, the aanchal", bn: "রং, বুটি, আঁচল" },
    { en: "The occasion it was woven for", bn: "কোন উপলক্ষে বোনা" },
    { en: "Its price, if you wish", bn: "চাইলে দাম" },
];

export default function Studio() {
    const { user } = useAuth();
    const staffish = isStaff(user);

    const [sarees, setSarees] = useState(null);
    const [qrId, setQrId] = useState("");

    const [recording, setRecording] = useState(false);
    const [seconds, setSeconds] = useState(0);
    const [audioBlob, setAudioBlob] = useState(null);
    const [audioUrl, setAudioUrl] = useState(null);
    const [busy, setBusy] = useState("");
    const [error, setError] = useState(null);
    const [transcript, setTranscript] = useState("");
    const [fields, setFields] = useState(null);
    const [published, setPublished] = useState(null);
    const [phone, setPhone] = useState("");
    const [shareResult, setShareResult] = useState(null);
    const [ondc, setOndc] = useState(null);
    const [showOndc, setShowOndc] = useState(false);

    const recRef = useRef(null);
    const chunksRef = useRef([]);
    const timerRef = useRef(null);

    useEffect(() => {
        if (staffish) api.get("/listings").then((r) => setSarees(r.data.listings)).catch(() => setSarees([]));
    }, [staffish]);

    if (!staffish) {
        return (
            <main className="weave-panel flex min-h-[60vh] flex-col items-center justify-center px-6 text-center" data-testid="studio-guard">
                <GoldSeal className="h-14 w-14" />
                <h1 className="font-display mt-4 text-2xl font-bold text-[#4a0d18]">The voice studio is for cooperative staff</h1>
                <p className="font-bengali mt-2 text-sm text-[#785c50]">ভয়েস স্টুডিও শুধু সমবায় কর্মীদের জন্য</p>
                <Link to="/login" className="luxe-btn mt-6 rounded-sm px-7 py-3 text-xs font-bold uppercase tracking-[0.25em]" data-testid="studio-guard-login">
                    Weaver login
                </Link>
            </main>
        );
    }

    const unlisted = (sarees || []).filter((s) => !s.listing);
    const anyDone = (sarees || []).filter((s) => s.ends_per_inch);

    const startRecording = async () => {
        setError(null);
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            recRef.current = new MediaRecorder(stream);
            chunksRef.current = [];
            recRef.current.ondataavailable = (e) => chunksRef.current.push(e.data);
            recRef.current.onstop = () => {
                const blob = new Blob(chunksRef.current, { type: "audio/webm" });
                setAudioBlob(blob);
                setAudioUrl(URL.createObjectURL(blob));
                stream.getTracks().forEach((t) => t.stop());
            };
            recRef.current.start();
            setRecording(true);
            setSeconds(0);
            timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
        } catch {
            setError("Microphone permission is needed for the voice studio. মাইক্রোফোনের অনুমতি দিন।");
        }
    };

    const stopRecording = () => {
        recRef.current?.stop();
        setRecording(false);
        clearInterval(timerRef.current);
    };

    const transcribe = async () => {
        setBusy("transcribe");
        setError(null);
        try {
            const fd = new FormData();
            fd.append("audio", audioBlob, "voice.webm");
            const r = await api.post("/transcribe", fd);
            setTranscript(r.data.transcript);
            setFields(r.data.fields || { title_bn: "", title_en: "", saree_type: "", colour: "", motif: "", occasion: "", price_inr: null, story_bn: "", story_en: "" });
        } catch (err) {
            setError(err?.response?.data?.detail || "Transcription failed — please try once more");
        } finally {
            setBusy("");
        }
    };

    const publish = async () => {
        setBusy("publish");
        setError(null);
        try {
            const payload = {
                title: fields.title_en || fields.title_bn || `Handloom ${fields.saree_type || "Saree"}`,
                price_inr: fields.price_inr ? Number(fields.price_inr) : null,
                story_bn: fields.story_bn || "",
                story_en: fields.story_en || "",
                occasion: fields.occasion || "",
                colour: fields.colour || "",
                motif: fields.motif || "",
                language: "bn",
            };
            const r = await api.post(`/listings/${qrId.trim()}`, payload);
            setPublished(r.data);
        } catch (err) {
            setError(err?.response?.data?.detail || "Could not publish the listing");
        } finally {
            setBusy("");
        }
    };

    const share = async () => {
        setBusy("share");
        try {
            const r = await api.post(`/listings/${qrId.trim()}/share`, { to: phone || null });
            setShareResult(r.data);
            if (!r.data.sent) window.open(r.data.share_url, "_blank");
        } catch (err) {
            setError(err?.response?.data?.detail || "Share failed");
        } finally {
            setBusy("");
        }
    };

    const loadOndc = async () => {
        try {
            const r = await api.get(`/ondc/${qrId.trim()}`);
            setOndc(JSON.stringify(r.data, null, 2));
            setShowOndc(true);
        } catch {
            setError("ONDC export not ready for this saree yet");
        }
    };

    const resetAll = () => {
        setPublished(null);
        setFields(null);
        setTranscript("");
        setAudioBlob(null);
        setAudioUrl(null);
        setQrId("");
        setShareResult(null);
        setOndc(null);
        api.get("/listings").then((r) => setSarees(r.data.listings)).catch(() => {});
    };

    return (
        <main className="mx-auto max-w-6xl px-6 py-12" data-testid="studio-page">
            <div className="text-center">
                <p className="eyebrow text-[#b08d2e]">Voice-to-commerce studio</p>
                <h1 className="font-display mt-3 text-3xl font-bold text-[#4a0d18] sm:text-4xl">Let the loom speak Bengali</h1>
                <p className="font-bengali mt-2 text-[#785c50]">কোনো টাইপিং নেই — শুধু বাংলায় বলুন, বাকিটা AI করবে</p>
                <PaisleyOrnament className="mx-auto mt-4 h-6 w-44 text-[#d4af37]" />
            </div>

            <div className="mt-10 grid gap-8 lg:grid-cols-[1fr_1.4fr]">
                {/* Left: saree picker + recorder */}
                <div className="space-y-6">
                    <section className="paper-grain rounded-sm border border-[#d4af37]/50 bg-white p-6" data-testid="studio-saree-picker">
                        <h3 className="font-display text-lg font-bold text-[#4a0d18]">1 · Choose a verified weave</h3>
                        <p className="font-bengali text-xs text-[#b08d2e]">যাচাইকৃত শাড়ি বাছুন</p>
                        {sarees === null ? (
                            <MandalaLoader className="mx-auto mt-4 h-10 w-10 text-[#b08d2e]" />
                        ) : unlisted.length ? (
                            <div className="mt-4 space-y-2.5" data-testid="studio-unlisted-list">
                                {unlisted.map((s) => (
                                    <button
                                        key={s.qr_id}
                                        data-testid={`studio-saree-option-${s.qr_id}`}
                                        onClick={() => setQrId(s.qr_id)}
                                        className={`flex w-full items-center gap-3 rounded-sm border p-2.5 text-left transition-colors ${
                                            qrId === s.qr_id ? "border-[#8b263e] bg-[#fff7ee]" : "border-[#d4af37]/40 hover:bg-[#fff7ee]/70"
                                        }`}
                                    >
                                        <img src={photoUrl(s.photo_url)} alt={s.saree_type} className="h-14 w-14 rounded-sm object-cover" />
                                        <span>
                                            <span className="block text-sm font-semibold text-[#4a0d18]">{s.saree_type} · {s.district}</span>
                                            <span className="tabular block font-mono text-[10px] tracking-widest text-[#a08a6e]">{s.qr_id} · EPI {s.ends_per_inch?.toFixed(0)}</span>
                                        </span>
                                    </button>
                                ))}
                            </div>
                        ) : (
                            <p className="mt-3 text-xs text-[#785c50]" data-testid="studio-none-unlisted">
                                Every verified weave already has its story. Register a new saree at the loom desk first.
                                <span className="font-bengali block">সব শাড়ির গল্প প্রকাশিত — আগে নতুন শাড়ি নিবন্ধন করুন।</span>
                            </p>
                        )}
                        {anyDone.length && !unlisted.length ? (
                            <input
                                data-testid="studio-qr-manual"
                                value={qrId}
                                onChange={(e) => setQrId(e.target.value.toUpperCase())}
                                placeholder="Or enter a verified QR ID"
                                className="mt-3 w-full rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-4 py-2.5 font-mono text-xs tracking-widest"
                            />
                        ) : null}
                    </section>

                    <section className="maroon-panel paper-grain relative overflow-hidden rounded-sm p-8 text-center text-[#f2e3c8]" data-testid="studio-recorder">
                        <CornerVine className="absolute right-0 top-0 h-14 w-14 text-[#d4af37]" flip />
                        <h3 className="font-display text-lg font-bold">2 · Speak the saree's story</h3>
                        <p className="font-bengali text-xs text-[#cbb490]">বাংলায় বলুন — নাম, কারুকাজ, রং, আঁচল, দাম, গল্প</p>
                        <div className="mt-6 flex justify-center">
                            <button
                                data-testid="studio-mic-button"
                                onClick={recording ? stopRecording : startRecording}
                                disabled={!qrId || (!recording && audioBlob)}
                                className={`relative flex h-24 w-24 items-center justify-center rounded-full border-2 border-[#d4af37] transition-all disabled:opacity-40 ${
                                    recording ? "pulse-ring bg-[#8b263e]" : "bg-[#3a0a13]/60 hover:bg-[#5e1220]"
                                }`}
                            >
                                <MicIcon className="h-9 w-9 text-[#e9d38a]" />
                            </button>
                        </div>
                        <p className="tabular mt-4 font-mono text-lg text-[#e9d38a]" data-testid="studio-timer">
                            {String(Math.floor(seconds / 60)).padStart(2, "0")}:{String(seconds % 60).padStart(2, "0")}
                        </p>
                        <p className="mt-1 text-[11px] uppercase tracking-[0.25em] text-[#cbb490]" data-testid="studio-record-state">
                            {recording ? "Recording · লেখা হচ্ছে" : audioBlob ? "Voice saved · ধারণকৃত" : qrId ? "Tap to speak" : "Choose a weave first"}
                        </p>
                        {audioUrl ? (
                            <div className="mt-4">
                                <audio src={audioUrl} controls className="mx-auto w-full max-w-xs" data-testid="studio-audio-playback" />
                                <button
                                    onClick={transcribe}
                                    disabled={busy === "transcribe"}
                                    data-testid="studio-transcribe-button"
                                    className="luxe-btn luxe-btn-gold mt-4 rounded-sm px-6 py-3 text-xs font-bold uppercase tracking-[0.2em] disabled:opacity-50"
                                >
                                    {busy === "transcribe" ? "Listening deeply…" : "AI, write my listing"}
                                    <span className="font-bengali text-xs font-normal opacity-80">AI লিখুক</span>
                                </button>
                            </div>
                        ) : null}
                        <ul className="mt-6 space-y-1.5 text-left text-xs text-[#d8c5a4]" data-testid="studio-prompts">
                            {PROMPTS.map((p) => (
                                <li key={p.en} className="flex items-center gap-2">
                                    <span className="text-[#d4af37]">❖</span> {p.en} <span className="font-bengali text-[#a98f68]">· {p.bn}</span>
                                </li>
                            ))}
                        </ul>
                    </section>
                </div>

                {/* Right: fields + publish */}
                <div className="space-y-6">
                    {error ? <p className="rounded-sm border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800" data-testid="studio-error">{error}</p> : null}

                    {transcript ? (
                        <section className="weave-panel rounded-sm border border-[#d4af37]/50 p-5" data-testid="studio-transcript">
                            <p className="eyebrow text-[#b08d2e]">The weaver said · <span className="font-bengali normal-case tracking-normal">তাঁতি বললেন</span></p>
                            <p className="font-bengali mt-2 text-sm leading-relaxed text-[#4a0d18]">“{transcript}”</p>
                        </section>
                    ) : null}

                    {fields ? (
                        <section className="paper-grain rounded-sm border border-[#d4af37]/50 bg-white p-6" data-testid="studio-fields">
                            <h3 className="font-display text-lg font-bold text-[#4a0d18]">3 · Touch the listing (optional)</h3>
                            <p className="font-bengali text-xs text-[#b08d2e]">ইচ্ছে হলে বদলান — না হলে সরাসরি প্রকাশ করুন</p>
                            <div className="mt-4 grid gap-3 sm:grid-cols-2">
                                {[
                                    { k: "title_en", l: "Title (English)" },
                                    { k: "title_bn", l: "নাম (বাংলা)", bn: true },
                                    { k: "colour", l: "Colour · রং" },
                                    { k: "motif", l: "Motif · বুটি" },
                                    { k: "occasion", l: "Occasion · উপলক্ষ" },
                                    { k: "price_inr", l: "Price ₹ · দাম", num: true },
                                ].map((f) => (
                                    <div key={f.k}>
                                        <label className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#785c50]">{f.l}</label>
                                        <input
                                            data-testid={`studio-field-${f.k}`}
                                            value={fields[f.k] ?? ""}
                                            onChange={(e) => setFields({ ...fields, [f.k]: e.target.value })}
                                            className={`mt-1 w-full rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-3 py-2.5 text-sm text-[#4a0d18] ${f.bn ? "font-bengali" : ""}`}
                                        />
                                    </div>
                                ))}
                            </div>
                            <div className="mt-3">
                                <label className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#785c50]">The weaver's story · <span className="font-bengali normal-case tracking-normal">গল্প (বাংলা)</span></label>
                                <textarea
                                    data-testid="studio-field-story-bn"
                                    value={fields.story_bn || ""}
                                    onChange={(e) => setFields({ ...fields, story_bn: e.target.value })}
                                    rows={3}
                                    className="font-bengali mt-1 w-full rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-3 py-2.5 text-sm text-[#4a0d18]"
                                />
                                <label className="mt-2 block text-[10px] font-bold uppercase tracking-[0.18em] text-[#785c50]">Story (English)</label>
                                <textarea
                                    data-testid="studio-field-story-en"
                                    value={fields.story_en || ""}
                                    onChange={(e) => setFields({ ...fields, story_en: e.target.value })}
                                    rows={3}
                                    className="mt-1 w-full rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-3 py-2.5 text-sm text-[#4a0d18]"
                                />
                            </div>
                            <button
                                onClick={publish}
                                disabled={busy === "publish" || !qrId}
                                data-testid="studio-publish-button"
                                className="luxe-btn mt-5 w-full justify-center rounded-sm px-6 py-3.5 text-sm font-bold uppercase tracking-[0.25em] disabled:opacity-50"
                            >
                                {busy === "publish" ? "Publishing…" : "Publish to the world"}
                                <span className="font-bengali text-xs font-normal opacity-80">প্রকাশ করুন</span>
                            </button>
                        </section>
                    ) : null}

                    {published ? (
                        <section className="rounded-sm border-2 border-[#d4af37] bg-white p-6" data-testid="studio-share-panel">
                            <div className="flex items-center gap-3">
                                <GoldSeal className="h-10 w-10" />
                                <div>
                                    <h3 className="font-display text-xl font-bold text-[#4a0d18]">The weave is live</h3>
                                    <p className="font-bengali text-xs text-[#b08d2e]">তালিকা প্রকাশিত — এখন ছড়িয়ে দিন</p>
                                </div>
                            </div>
                            <div className="mt-5 space-y-3">
                                <label className="text-[10px] font-bold uppercase tracking-[0.18em] text-[#785c50]">Buyer's WhatsApp number · <span className="font-bengali normal-case tracking-normal">ক্রেতার নম্বর</span></label>
                                <div className="flex gap-2">
                                    <input
                                        data-testid="studio-share-phone"
                                        value={phone}
                                        onChange={(e) => setPhone(e.target.value)}
                                        placeholder="9xxxxxxxxx"
                                        className="tabular flex-1 rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-4 py-2.5 text-sm tracking-wider"
                                    />
                                    <button
                                        onClick={share}
                                        disabled={busy === "share"}
                                        data-testid="studio-share-button"
                                        className="luxe-btn luxe-btn-gold rounded-sm px-5 py-2.5 text-xs font-bold uppercase tracking-[0.18em] disabled:opacity-50"
                                    >
                                        {busy === "share" ? "Sending…" : shareResult?.sent ? "Sent ✓" : "Send on WhatsApp"}
                                    </button>
                                </div>
                                {shareResult && !shareResult.sent ? (
                                    <p className="text-[11px] text-[#785c50]" data-testid="studio-share-fallback">
                                        WhatsApp Business isn't connected yet, so a click-to-chat window opened with the listing
                                        pre-filled. Add your WABA credentials to send automatically.{" "}
                                        <a href={shareResult.share_url} target="_blank" rel="noreferrer" className="font-bold text-[#8b263e] underline" data-testid="studio-share-fallback-link">
                                            Open again
                                        </a>
                                    </p>
                                ) : null}
                                {shareResult?.sent ? (
                                    <p className="text-xs text-green-800" data-testid="studio-share-sent">Delivered to the buyer's WhatsApp — with the certificate link inside.</p>
                                ) : null}

                                <div className="flex flex-wrap gap-2 pt-2">
                                    <button onClick={loadOndc} data-testid="studio-ondc-button" className="luxe-btn luxe-btn-ghost rounded-sm px-5 py-2.5 text-xs font-bold uppercase tracking-[0.18em]">
                                        ONDC payload
                                    </button>
                                    <a href={published.certificate_url} target="_blank" rel="noreferrer" data-testid="studio-cert-link" className="luxe-btn luxe-btn-ghost rounded-sm px-5 py-2.5 text-xs font-bold uppercase tracking-[0.18em]">
                                        View certificate
                                    </a>
                                    <button onClick={resetAll} data-testid="studio-new-listing" className="luxe-btn rounded-sm px-5 py-2.5 text-xs font-bold uppercase tracking-[0.18em]">
                                        New listing
                                    </button>
                                </div>
                            </div>
                        </section>
                    ) : null}
                </div>
            </div>

            {showOndc && ondc ? (
                <div className="fixed inset-0 z-[80] flex items-center justify-center bg-[#3a0a13]/90 p-4" onClick={() => setShowOndc(false)} data-testid="studio-ondc-modal">
                    <div className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-sm bg-[#2c1810] p-6" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-between">
                            <p className="eyebrow text-[#e9d38a]">ONDC-ready catalogue item</p>
                            <button onClick={() => navigator.clipboard?.writeText(ondc)} data-testid="studio-ondc-copy" className="text-xs uppercase tracking-[0.2em] text-[#e9d38a] underline">
                                Copy
                            </button>
                        </div>
                        <pre className="mt-4 overflow-x-auto text-[11px] leading-relaxed text-[#cbb490]">{ondc}</pre>
                    </div>
                </div>
            ) : null}
        </main>
    );
}

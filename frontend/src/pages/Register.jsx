import { Link } from "react-router-dom";
import { api, auth, photoUrl, isStaff } from "@/lib/api";
import { useAuth } from "@/pages/Login";
import { bn, CornerVine, GoldSeal, LoomIcon, MandalaLoader, PaisleyOrnament } from "@/components/motifs";

const SAREE_TYPES = ["Tant", "Jamdani", "Baluchari", "Kantha", "Gorod", "Other"];

const StepHead = ({ n, title, bnTitle, testid }) => (
    <div className="flex items-center gap-3" data-testid={testid}>
        <span className="maroon-panel font-display flex h-10 w-10 items-center justify-center rounded-full border border-[#d4af37]/70 text-lg font-bold text-[#e9d38a]">
            {bn(n)}
        </span>
        <div>
            <h3 className="font-display text-lg font-bold text-[#4a0d18]">{title}</h3>
            <p className="font-bengali text-xs text-[#b08d2e]">{bnTitle}</p>
        </div>
    </div>
);

export default function Register() {
    const { user, refresh } = useAuth();
    const staffish = isStaff(user);

    const [weavers, setWeavers] = useState([]);
    const [blankIds, setBlankIds] = useState([]);
    const [summary, setSummary] = useState(null);
    const [recent, setRecent] = useState([]);

    const [weaverId, setWeaverId] = useState("");
    const [sareeType, setSareeType] = useState("Tant");
    const [batchId, setBatchId] = useState("");
    const [qrId, setQrId] = useState("");
    const [files, setFiles] = useState([]);
    const [busy, setBusy] = useState("");
    const [error, setError] = useState(null);
    const [result, setResult] = useState(null);

    const [tagCount, setTagCount] = useState(54);
    const [tagPdf, setTagPdf] = useState(null);

    const pollRef = useRef(null);

    const loadSide = () => {
        api.get("/weavers").then((r) => setWeavers(r.data)).catch(() => {});
        api.get("/tags/blank").then((r) => setBlankIds(r.data.qr_ids)).catch(() => {});
        api.get("/portal/summary").then((r) => setSummary(r.data)).catch(() => {});
        api.get("/batches/recent").then((r) => setRecent(r.data.batches)).catch(() => {});
    };

    useEffect(() => {
        if (staffish) loadSide();
        return () => clearInterval(pollRef.current);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [staffish]);

    if (!staffish) {
        return (
            <main className="weave-panel flex min-h-[60vh] flex-col items-center justify-center px-6 text-center" data-testid="register-guard">
                <GoldSeal className="h-14 w-14" />
                <h1 className="font-display mt-4 text-2xl font-bold text-[#4a0d18]">The loom desk is for cooperative staff</h1>
                <p className="font-bengali mt-2 text-sm text-[#785c50]">তাঁত-ডেস্ক শুধু সমবায় কর্মীদের জন্য</p>
                <Link to="/login" className="luxe-btn mt-6 rounded-sm px-7 py-3 text-xs font-bold uppercase tracking-[0.25em]" data-testid="register-guard-login">
                    Weaver login
                </Link>
            </main>
        );
    }

    const startBatch = async () => {
        setBusy("batch");
        setError(null);
        try {
            const r = await api.post("/batch", { weaver_id: weaverId, saree_type: sareeType });
            setBatchId(r.data.batch_id);
        } catch (err) {
            setError(err?.response?.data?.message_en || err?.response?.data?.detail || "Could not start batch");
        } finally {
            setBusy("");
        }
    };

    const submitRegistration = async () => {
        setBusy("register");
        setError(null);
        try {
            const uploadId = crypto.randomUUID();
            const fd = new FormData();
            fd.append("qr_id", qrId.trim());
            fd.append("batch_id", batchId);
            fd.append("upload_id", uploadId);
            fd.append("phone_model", (navigator.userAgent || "web").slice(0, 90));
            files.slice(0, 5).forEach((f) => fd.append("photos", f));
            await api.post("/saree", fd);
            setResult({ qr_id: qrId.trim(), status: "queued" });

            pollRef.current = setInterval(async () => {
                try {
                    const r = await api.get(`/saree/${qrId.trim()}`);
                    if (r.data.status === "done" || r.data.status === "failed") {
                        clearInterval(pollRef.current);
                        setResult({ qr_id: qrId.trim(), ...r.data });
                        loadSide();
                    } else {
                        setResult((prev) => ({ ...prev, status: r.data.status }));
                    }
                } catch {
                    clearInterval(pollRef.current);
                }
            }, 2500);
        } catch (err) {
            setError(err?.response?.data?.message_en || err?.response?.data?.detail || "Registration failed");
        } finally {
            setBusy("");
        }
    };

    const generateTags = async () => {
        setBusy("tags");
        try {
            const r = await api.post("/tags/generate", { count: tagCount });
            setTagPdf(r.data);
        } catch (err) {
            setError(err?.response?.data?.detail || "Tag generation failed");
        } finally {
            setBusy("");
        }
    };

    const reset = () => {
        setBatchId("");
        setQrId("");
        setFiles([]);
        setResult(null);
        loadSide();
    };

    return (
        <main className="mx-auto max-w-7xl px-6 py-12" data-testid="register-page">
            <div className="text-center">
                <p className="eyebrow text-[#b08d2e]">Loom-side register</p>
                <h1 className="font-display mt-3 text-3xl font-bold text-[#4a0d18] sm:text-4xl">Give this weave its witness</h1>
                <p className="font-bengali mt-2 text-[#785c50]">তাঁতের পাশেই নিবন্ধন — সুতোর সাক্ষী তৈরি হোক</p>
                <PaisleyOrnament className="mx-auto mt-4 h-6 w-44 text-[#d4af37]" />
            </div>

            <div className="mt-10 grid gap-8 lg:grid-cols-[1.6fr_1fr]">
                <div className="space-y-6" data-testid="register-flow">
                    {/* Step 1 */}
                    <section className="paper-grain rounded-sm border border-[#d4af37]/50 bg-white p-6" data-testid="register-step-batch">
                        <StepHead n={1} title="Open a registration batch" bnTitle="ব্যাচ খুলুন" testid="register-step-1" />
                        <div className="mt-4 grid gap-4 sm:grid-cols-2">
                            <div>
                                <label className="text-[11px] font-bold uppercase tracking-[0.2em] text-[#785c50]">Master weaver · <span className="font-bengali normal-case tracking-normal">তাঁতি</span></label>
                                <select
                                    data-testid="register-weaver-select"
                                    value={weaverId}
                                    onChange={(e) => setWeaverId(e.target.value)}
                                    className="mt-1.5 w-full rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-4 py-3 text-sm text-[#4a0d18]"
                                >
                                    <option value="">— choose the weaver —</option>
                                    {weavers.map((w) => (
                                        <option key={w.id} value={w.id}>{w.name}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="text-[11px] font-bold uppercase tracking-[0.2em] text-[#785c50]">Craft · <span className="font-bengali normal-case tracking-normal">কারুকাজ</span></label>
                                <div className="mt-1.5 flex flex-wrap gap-1.5">
                                    {SAREE_TYPES.map((t) => (
                                        <button
                                            key={t}
                                            type="button"
                                            data-testid={`register-craft-chip-${t.toLowerCase()}`}
                                            onClick={() => setSareeType(t)}
                                            className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors ${
                                                sareeType === t ? "border-[#4a0d18] bg-[#4a0d18] text-[#e9d38a]" : "border-[#d4af37]/60 text-[#5e1220] hover:bg-[#fff7ee]"
                                            }`}
                                        >
                                            {t}
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                        {batchId ? (
                            <p className="mt-4 rounded-sm border border-green-300 bg-green-50 px-4 py-2.5 font-mono text-xs tracking-wider text-green-900" data-testid="register-batch-created">
                                Batch live · {batchId}
                            </p>
                        ) : (
                            <button
                                onClick={startBatch}
                                disabled={!weaverId || busy === "batch"}
                                data-testid="register-start-batch-button"
                                className="luxe-btn mt-5 rounded-sm px-6 py-3 text-xs font-bold uppercase tracking-[0.2em] disabled:opacity-50"
                            >
                                {busy === "batch" ? "Opening…" : "Start batch"}
                            </button>
                        )}
                    </section>

                    {/* Step 2 */}
                    <section className={`paper-grain rounded-sm border p-6 transition-opacity ${batchId ? "border-[#d4af37]/50 bg-white" : "border-[#d4af37]/25 bg-white/50 opacity-60"}`} data-testid="register-step-tag">
                        <StepHead n={2} title="Pick the gold QR tag" bnTitle="সোনালি QR ট্যাগ বাছুন" testid="register-step-2" />
                        <div className="mt-4 grid gap-4 sm:grid-cols-2">
                            <div>
                                <label className="text-[11px] font-bold uppercase tracking-[0.2em] text-[#785c50]">Blank tags · <span className="font-bengali normal-case tracking-normal">খালি ট্যাগ</span></label>
                                <select
                                    data-testid="register-tag-select"
                                    value={blankIds.includes(qrId) ? qrId : ""}
                                    onChange={(e) => setQrId(e.target.value)}
                                    disabled={!batchId}
                                    className="mt-1.5 w-full rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-4 py-3 font-mono text-sm tracking-widest text-[#4a0d18]"
                                >
                                    <option value="">— select a printed tag —</option>
                                    {blankIds.map((id) => (
                                        <option key={id} value={id}>{id}</option>
                                    ))}
                                </select>
                            </div>
                            <div>
                                <label className="text-[11px] font-bold uppercase tracking-[0.2em] text-[#785c50]">Or type it · <span className="font-bengali normal-case tracking-normal">অথবা লিখুন</span></label>
                                <input
                                    data-testid="register-tag-input"
                                    value={qrId}
                                    onChange={(e) => setQrId(e.target.value.toUpperCase())}
                                    disabled={!batchId}
                                    placeholder="TS-XXXXXX"
                                    className="mt-1.5 w-full rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-4 py-3 font-mono text-sm tracking-widest text-[#4a0d18]"
                                />
                            </div>
                        </div>
                    </section>

                    {/* Step 3 */}
                    <section className={`paper-grain rounded-sm border p-6 transition-opacity ${batchId && qrId ? "border-[#d4af37]/50 bg-white" : "border-[#d4af37]/25 bg-white/50 opacity-60"}`} data-testid="register-step-photos">
                        <StepHead n={3} title="Capture the weave in the jig" bnTitle="জিগে বুননের ছবি তুলুন" testid="register-step-3" />
                        <p className="mt-3 text-xs leading-relaxed text-[#785c50]">
                            Place the saree flat inside the optical jig card. Capture a burst of 1–5 steady photos — the engine
                            will choose the sharpest frames and count the threads by physics.
                            <span className="font-bengali block">জিগ-কার্ডের ভিতরে শাড়ি বিছিয়ে ১–৫টি স্থির ছবি তুলুন।</span>
                        </p>
                        <input
                            data-testid="register-photo-input"
                            type="file"
                            accept="image/*"
                            capture="environment"
                            multiple
                            disabled={!batchId || !qrId}
                            onChange={(e) => setFiles(Array.from(e.target.files || []).slice(0, 5))}
                            className="mt-4 text-xs text-[#5e4936] file:mr-3 file:rounded-sm file:border-0 file:bg-[#4a0d18] file:px-4 file:py-2 file:text-xs file:font-semibold file:text-[#e9d38a]"
                        />
                        {files.length ? (
                            <div className="mt-4 flex flex-wrap gap-2" data-testid="register-photo-previews">
                                {files.map((f, i) => (
                                    <img key={i} src={URL.createObjectURL(f)} alt={`burst ${i + 1}`} className="gold-frame h-20 w-20 rounded-sm object-cover" />
                                ))}
                            </div>
                        ) : null}
                        <button
                            onClick={submitRegistration}
                            disabled={!batchId || !qrId || !files.length || busy === "register"}
                            data-testid="register-submit-button"
                            className="luxe-btn mt-5 rounded-sm px-7 py-3 text-xs font-bold uppercase tracking-[0.2em] disabled:opacity-50"
                        >
                            {busy === "register" ? "Uploading the burst…" : "Register this saree"}
                        </button>
                    </section>

                    {/* Step 4 */}
                    {result ? (
                        <section className="rounded-sm border border-[#d4af37]/60 bg-white p-6" data-testid="register-result-panel">
                            <StepHead n={4} title="The engine's verdict" bnTitle="ইঞ্জিনের রায়" testid="register-step-4" />
                            {result.status === "done" ? (
                                <div className="mt-4 text-center" data-testid="register-result-done">
                                    <p className="font-bengali text-sm text-[#5e1220]">বুনন যাচাই হয়েছে — জন্ম সনদ প্রস্তুত</p>
                                    <div className="mt-4 grid grid-cols-3 gap-3">
                                        <div className="weave-panel rounded-sm border border-[#d4af37]/40 py-4">
                                            <p className="tabular font-display text-3xl font-bold text-[#5e1220]" data-testid="result-epi">{result.ends_per_inch?.toFixed(1)}</p>
                                            <p className="text-[10px] uppercase tracking-[0.2em] text-[#785c50]">EPI</p>
                                        </div>
                                        <div className="weave-panel rounded-sm border border-[#d4af37]/40 py-4">
                                            <p className="tabular font-display text-3xl font-bold text-[#5e1220]" data-testid="result-ppi">{result.picks_per_inch?.toFixed(1)}</p>
                                            <p className="text-[10px] uppercase tracking-[0.2em] text-[#785c50]">PPI</p>
                                        </div>
                                        <div className="maroon-panel rounded-sm border border-[#d4af37]/40 py-4">
                                            <p className="font-display text-3xl font-bold text-[#e9d38a]" data-testid="result-grade">{result.grade || "P"}</p>
                                            <p className="text-[10px] uppercase tracking-[0.2em] text-[#d8c5a4]">{result.grade ? "Grade" : "Provisional"}</p>
                                        </div>
                                    </div>
                                    <a href={`/c/${result.qr_id}`} data-testid="result-certificate-link" className="luxe-btn luxe-btn-gold mt-5 rounded-sm px-6 py-3 text-xs font-bold uppercase tracking-[0.2em]">
                                        Open its birth certificate
                                    </a>
                                    <button onClick={reset} data-testid="result-register-another" className="luxe-btn luxe-btn-ghost ml-2 mt-5 rounded-sm px-6 py-3 text-xs font-bold uppercase tracking-[0.2em]">
                                        Register another
                                    </button>
                                </div>
                            ) : result.status === "failed" ? (
                                <div className="mt-4 rounded-sm border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900" data-testid="register-result-failed">
                                    <b>Quality gates said no.</b>
                                    <p>{result.reason}</p>
                                    {result.reason_bn ? <p className="font-bengali text-xs">{result.reason_bn}</p> : null}
                                    <p className="mt-2 text-xs">The tag was released — retake the photos and register again. ট্যাগ ছেড়ে দেওয়া হয়েছে, আবার চেষ্টা করুন।</p>
                                    <button onClick={reset} className="luxe-btn luxe-btn-ghost mt-3 rounded-sm px-5 py-2 text-xs font-bold uppercase tracking-[0.2em]" data-testid="result-retry-button">
                                        Retake
                                    </button>
                                </div>
                            ) : (
                                <div className="mt-5 text-center" data-testid="register-result-processing">
                                    <MandalaLoader className="mx-auto h-16 w-16 text-[#b08d2e]" />
                                    <p className="mt-3 text-sm uppercase tracking-[0.25em] text-[#785c50]">
                                        {result.status === "queued" ? "In the queue" : "Counting threads"}…
                                    </p>
                                    <p className="font-bengali text-xs text-[#a08a6e]">সুতো গণনা চলছে</p>
                                </div>
                            )}
                        </section>
                    ) : null}

                    {error ? (
                        <p className="rounded-sm border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800" data-testid="register-error">
                            {error}
                        </p>
                    ) : null}
                </div>

                {/* Side rail */}
                <aside className="space-y-6">
                    <section className="maroon-panel paper-grain rounded-sm p-6 text-[#f2e3c8]" data-testid="register-summary">
                        <div className="flex items-center gap-2">
                            <LoomIcon className="h-5 w-5 text-[#e9d38a]" />
                            <h3 className="font-display text-lg font-bold">Your co-op today</h3>
                        </div>
                        <p className="font-bengali text-xs text-[#cbb490]">আজকের সমবায়</p>
                        {summary ? (
                            <div className="mt-4 grid grid-cols-2 gap-3 text-center">
                                {[
                                    { v: summary.tags.blank, l: "Blank tags", b: "খালি ট্যাগ" },
                                    { v: summary.sarees_done, l: "Verified", b: "যাচাইকৃত" },
                                    { v: summary.listings_published, l: "Listings", b: "তালিকা" },
                                    { v: `${summary.avg_epi}×${summary.avg_ppi}`, l: "Avg / inch", b: "গড় ঘনত্ব" },
                                ].map((s) => (
                                    <div key={s.l} className="rounded-sm border border-[#d4af37]/40 bg-[#3a0a13]/40 px-2 py-3">
                                        <p className="tabular font-display text-2xl font-bold text-[#e9d38a]" data-testid="summary-value">{s.v ?? 0}</p>
                                        <p className="text-[10px] uppercase tracking-[0.18em] text-[#cbb490]">{s.l}</p>
                                        <p className="font-bengali text-[10px] text-[#a98f68]">{s.b}</p>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <MandalaLoader className="mx-auto mt-6 h-12 w-12 text-[#b08d2e]" />
                        )}
                    </section>

                    <section className="paper-grain rounded-sm border border-[#d4af37]/50 bg-white p-6" data-testid="register-tags-tool">
                        <h3 className="font-display text-lg font-bold text-[#4a0d18]">Print new QR tags</h3>
                        <p className="font-bengali text-xs text-[#b08d2e]">নতুন QR ট্যাগ শিট ছাপুন</p>
                        <div className="mt-3 flex items-center gap-3">
                            <select
                                data-testid="tags-count-select"
                                value={tagCount}
                                onChange={(e) => setTagCount(Number(e.target.value))}
                                className="rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-3 py-2.5 text-sm text-[#4a0d18]"
                            >
                                <option value={27}>27 tags</option>
                                <option value={54}>54 tags (A4)</option>
                                <option value={108}>108 tags</option>
                            </select>
                            <button onClick={generateTags} disabled={busy === "tags"} data-testid="tags-generate-button" className="luxe-btn rounded-sm px-5 py-2.5 text-xs font-bold uppercase tracking-[0.2em] disabled:opacity-50">
                                {busy === "tags" ? "Weaving IDs…" : "Generate"}
                            </button>
                        </div>
                        {tagPdf ? (
                            <div className="mt-3 rounded-sm border border-green-300 bg-green-50 px-4 py-3 text-xs text-green-900" data-testid="tags-generate-result">
                                <p className="font-mono tracking-wider">{tagPdf.batch_no}</p>
                                <a href={photoUrl(tagPdf.pdf_url)} target="_blank" rel="noreferrer" data-testid="tags-pdf-link" className="mt-1 inline-block font-bold uppercase tracking-[0.2em] text-[#8b263e] underline">
                                    Download printable PDF
                                </a>
                            </div>
                        ) : null}
                    </section>

                    <section className="rounded-sm border border-[#d4af37]/50 bg-white p-6" data-testid="register-recent-batches">
                        <h3 className="font-display text-lg font-bold text-[#4a0d18]">Recent batches</h3>
                        <p className="font-bengali text-xs text-[#b08d2e]">সাম্প্রতিক ব্যাচ</p>
                        <ul className="mt-3 space-y-2.5">
                            {recent.map((b) => (
                                <li key={b.batch_id} className="border-b border-[#d4af37]/25 pb-2.5 text-xs" data-testid="recent-batch-row">
                                    <p className="font-semibold text-[#4a0d18]">{b.weaver} · {b.saree_type}</p>
                                    <p className="font-mono text-[10px] tracking-wider text-[#a08a6e]">{b.batch_id}</p>
                                </li>
                            ))}
                            {!recent.length ? <li className="text-xs text-[#a08a6e]">No batches yet today.</li> : null}
                        </ul>
                    </section>
                </aside>
            </div>
        </main>
    );
} import React, { useContext, useEffect, useRef, useState } from "react";

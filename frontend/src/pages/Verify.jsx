import React, { useContext, useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import Certificate from "@/components/Certificate";
import { MandalaLoader, PaisleyOrnament, QrIcon } from "@/components/motifs";
import { useAuth } from "@/pages/Login";
import { canVerify } from "@/lib/api";

function Recheck() {
    const [qrId, setQrId] = useState("");
    const [files, setFiles] = useState([]);
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        setResult(null);
        try {
            const fd = new FormData();
            fd.append("upload_id", crypto.randomUUID());
            files.slice(0, 3).forEach((f) => fd.append("photos", f));
            const r = await api.post(`/verify/${qrId.trim()}`, fd);
            setResult(r.data);
        } catch (err) {
            setError(err?.response?.data?.message_en || err?.response?.data?.detail || "Verification failed");
        } finally {
            setBusy(false);
        }
    };

    const tone = result?.result === "genuine" ? "green" : result?.result === "no_match" ? "red" : "amber";
    const tones = {
        green: "border-green-400 bg-green-50 text-green-900",
        red: "border-red-400 bg-red-50 text-red-900",
        amber: "border-amber-400 bg-amber-50 text-amber-900",
    };

    return (
        <form onSubmit={submit} className="mt-8 rounded-sm border border-[#d4af37]/50 bg-white p-6" data-testid="verify-recheck-card">
            <p className="eyebrow text-[#b08d2e]">Seller & staff tool</p>
            <h3 className="font-display mt-2 text-xl font-bold text-[#4a0d18]">Fabric re-check</h3>
            <p className="font-bengali text-xs text-[#785c50]">কাপড়ের পুনঃযাচাই — নতুন ছবিতে ফিঙ্গারপ্রিন্ট মেলান</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
                <input
                    data-testid="recheck-qr-input"
                    value={qrId}
                    onChange={(e) => setQrId(e.target.value)}
                    placeholder="QR ID e.g. TS-XXXXXX"
                    required
                    className="rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-4 py-2.5 font-mono text-sm tracking-widest text-[#4a0d18]"
                />
                <input
                    data-testid="recheck-photo-input"
                    type="file"
                    accept="image/*"
                    capture="environment"
                    multiple
                    onChange={(e) => setFiles(Array.from(e.target.files || []))}
                    className="text-xs text-[#5e4936] file:mr-3 file:rounded-sm file:border-0 file:bg-[#4a0d18] file:px-3 file:py-1.5 file:text-xs file:text-[#e9d38a]"
                />
            </div>
            {files.length ? <p className="mt-2 text-xs text-[#785c50]">{files.length} photo(s) attached</p> : null}
            <button
                type="submit"
                disabled={busy || !files.length}
                data-testid="recheck-submit-button"
                className="luxe-btn mt-4 rounded-sm px-6 py-2.5 text-xs font-bold uppercase tracking-[0.2em] disabled:opacity-50"
            >
                {busy ? "Matching fingerprint…" : "Check authenticity"}
            </button>

            {error ? <p className="mt-3 text-sm text-red-700" data-testid="recheck-error">{error}</p> : null}
            {result ? (
                <div className={`mt-4 rounded-sm border px-4 py-3 text-sm ${tones[tone]}`} data-testid="recheck-result">
                    <b className="uppercase tracking-widest">{result.result}</b>
                    {result.score != null ? <span className="ml-2 font-mono text-xs">match score {result.score.toFixed(3)}</span> : null}
                    {result.message_en ? <p className="mt-1">{result.message_en}</p> : null}
                    {result.message_bn ? <p className="font-bengali text-xs">{result.message_bn}</p> : null}
                </div>
            ) : null}
        </form>
    );
}

export default function Verify() {
    const { user } = useAuth();
    const { qrId: routeId } = useParams();
    const [qrId, setQrId] = useState(routeId || "");
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();

    const inspect = async (id) => {
        if (!id) return;
        setLoading(true);
        try {
            const r = await api.get(`/certificates/${id.trim()}`);
            setData(r.data);
            if (!routeId) window.history.replaceState(null, "", `/verify?qr=${id.trim()}`);
        } catch {
            setData({ state: "unknown", qr_id: id });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        const q = new URLSearchParams(window.location.search).get("qr");
        const id = routeId || q;
        if (id) {
            setQrId(id);
            inspect(id);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [routeId]);

    return (
        <main className="mx-auto max-w-5xl px-6 py-14" data-testid="verify-page">
            <div className="text-center">
                <p className="eyebrow text-[#b08d2e]">Buyer's inspector</p>
                <h1 className="font-display mt-3 text-3xl font-bold text-[#4a0d18] sm:text-4xl">Inspect the weave</h1>
                <p className="font-bengali mt-2 text-[#785c50]">বুনন যাচাই করুন — ট্যাগের আইডি লিখুন বা স্ক্যান করুন</p>
                <PaisleyOrnament className="mx-auto mt-4 h-6 w-44 text-[#d4af37]" />
            </div>

            <form
                onSubmit={(e) => {
                    e.preventDefault();
                    inspect(qrId);
                }}
                className="mx-auto mt-8 flex max-w-xl flex-col gap-3 sm:flex-row"
            >
                <div className="relative flex-1">
                    <QrIcon className="absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-[#b08d2e]" />
                    <input
                        data-testid="verify-qr-input"
                        value={qrId}
                        onChange={(e) => setQrId(e.target.value.toUpperCase())}
                        placeholder="Enter tag ID — TS-XXXXXX"
                        className="w-full rounded-sm border border-[#d4af37]/60 bg-white py-3.5 pl-11 pr-4 font-mono text-sm tracking-[0.25em] text-[#4a0d18] focus:border-[#8b263e]"
                    />
                </div>
                <button type="submit" data-testid="verify-submit-button" className="luxe-btn justify-center rounded-sm px-7 py-3 text-xs font-bold uppercase tracking-[0.25em]">
                    {loading ? "Consulting the loom…" : "Inspect"}
                </button>
            </form>

            <div className="mx-auto mt-4 flex max-w-xl flex-wrap items-center justify-center gap-2 text-xs text-[#785c50]" data-testid="verify-demo-chips">
                <span className="uppercase tracking-[0.2em]">Try live:</span>
                {["TS-HXW92XBU", "TS-BBT6J45C"].map((id) => (
                    <button
                        key={id}
                        type="button"
                        data-testid={`verify-demo-chip-${id}`}
                        onClick={() => {
                            setQrId(id);
                            inspect(id);
                        }}
                        className="rounded-full border border-[#d4af37]/60 bg-white px-3 py-1 font-mono text-[11px] tracking-widest text-[#5e1220] transition-colors hover:bg-[#fff7ee]"
                    >
                        {id}
                    </button>
                ))}
            </div>

            <div className="mt-10">
                {loading ? (
                    <MandalaLoader className="mx-auto h-20 w-20 text-[#b08d2e]" />
                ) : data ? (
                    <Certificate data={data} />
                ) : (
                    <div className="mx-auto max-w-xl rounded-sm border border-dashed border-[#d4af37]/60 bg-white/60 p-10 text-center text-sm text-[#785c50]" data-testid="verify-empty-state">
                        Every genuine TantSaakshi saree wears a gold QR tag. Enter its ID — or scan the tag with your phone
                        camera — and its digital birth certificate opens right here.
                        <span className="font-bengali mt-2 block">প্রতিটি বৈধ শাড়িতে সোনালি QR ট্যাগ থাকে। স্ক্যান করলেই জন্ম সনদ খুলে যায়।</span>
                    </div>
                )}
            </div>

            {user && canVerify(user) ? <div className="mx-auto max-w-2xl"><Recheck /></div> : null}
        </main>
    );
}

export function ScanCert() {
    const { qrId } = useParams();
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    useEffect(() => {
        let alive = true;
        api.get(`/certificates/${qrId}`)
            .then((r) => alive && setData(r.data))
            .catch(() => alive && setData({ state: "unknown", qr_id: qrId }))
            .finally(() => alive && setLoading(false));
        return () => {
            alive = false;
        };
    }, [qrId]);

    return (
        <main className="weave-panel min-h-[80vh] px-4 py-12" data-testid="scan-cert-page">
            <button onClick={() => navigate("/")} className="mx-auto mb-8 block text-center text-[11px] uppercase tracking-[0.3em] text-[#b08d2e]" data-testid="scan-brand-home">
                TantSaakshi · তাঁতসাক্ষী
            </button>
            {loading ? <MandalaLoader className="mx-auto h-20 w-20 text-[#b08d2e]" /> : <Certificate data={data} />}
        </main>
    );
}

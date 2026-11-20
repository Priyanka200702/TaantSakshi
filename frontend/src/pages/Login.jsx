import React, { useContext, useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api, auth, apiErrorText } from "@/lib/api";
import { PaisleyOrnament } from "@/components/motifs";

export const AuthCtx = React.createContext({ user: null, refresh: () => {} });

export function useAuth() {
    return useContext(AuthCtx);
}

export default function Login() {
    const { refresh } = useAuth();
    const [phone, setPhone] = useState("");
    const [pin, setPin] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [redirect, setRedirect] = useState(null);

    const submit = async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
            const r = await api.post("/login", { phone: phone.trim(), pin: pin.trim() });
            auth.set({ ...r.data, phone: phone.trim() });
            refresh();
            setRedirect(r.data.role === "seller" ? "/verify" : "/register");
        } catch (err) {
            setError({
                en: apiErrorText(err, "en"),
                bn: apiErrorText(err, "bn"),
            });
        } finally {
            setBusy(false);
        }
    };

    if (redirect) return <Navigate to={redirect} replace />;

    return (
        <main className="weave-panel flex min-h-[70vh] items-center justify-center px-6 py-16" data-testid="login-page">
            <div className="paper-grain w-full max-w-md rounded-sm border border-[#d4af37]/50 bg-white p-8 shadow-[0_30px_60px_-30px_rgba(58,10,19,0.45)] sm:p-10">
                <div className="text-center">
                    <p className="eyebrow text-[#b08d2e]">Loom-side access</p>
                    <h1 className="font-display mt-3 text-3xl font-bold text-[#4a0d18]">Weaver & Co-op Login</h1>
                    <p className="font-bengali mt-1 text-sm text-[#785c50]">সমবায় কর্মী ও বিক্রেতার প্রবেশ</p>
                    <PaisleyOrnament className="mx-auto mt-4 h-6 w-40 text-[#d4af37]" />
                </div>

                <form onSubmit={submit} className="mt-8 space-y-5">
                    <div>
                        <label className="text-[11px] font-bold uppercase tracking-[0.2em] text-[#785c50]" htmlFor="phone">
                            Phone <span className="font-bengali normal-case tracking-normal">· ফোন</span>
                        </label>
                        <input
                            id="phone"
                            data-testid="login-phone-input"
                            type="tel"
                            required
                            value={phone}
                            onChange={(e) => setPhone(e.target.value)}
                            placeholder="9876543210"
                            className="tabular mt-1.5 w-full rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-4 py-3 text-lg tracking-wider text-[#4a0d18] focus:border-[#8b263e]"
                        />
                    </div>
                    <div>
                        <label className="text-[11px] font-bold uppercase tracking-[0.2em] text-[#785c50]" htmlFor="pin">
                            Secret PIN <span className="font-bengali normal-case tracking-normal">· গোপন পিন</span>
                        </label>
                        <input
                            id="pin"
                            data-testid="login-pin-input"
                            type="password"
                            required
                            value={pin}
                            onChange={(e) => setPin(e.target.value)}
                            placeholder="••••••"
                            className="tabular mt-1.5 w-full rounded-sm border border-[#d4af37]/60 bg-[#fff7ee] px-4 py-3 text-lg tracking-[0.4em] text-[#4a0d18] focus:border-[#8b263e]"
                        />
                    </div>

                    {error ? (
                        <div data-testid="login-error" className="rounded-sm border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
                            {error.en}
                            <span className="font-bengali block text-xs text-red-600">{error.bn}</span>
                        </div>
                    ) : null}

                    <button
                        type="submit"
                        disabled={busy}
                        data-testid="login-submit-button"
                        className="luxe-btn w-full justify-center rounded-sm px-6 py-3.5 text-sm font-bold uppercase tracking-[0.25em] disabled:opacity-60"
                    >
                        {busy ? "Opening the loom…" : "Enter"}
                        <span className="font-bengali text-xs font-normal opacity-80">প্রবেশ</span>
                    </button>
                </form>

                <p className="mt-6 text-center text-[11px] leading-relaxed text-[#a08a6e]">
                    For cooperative staff, authorised sellers and administrators.
                    <span className="font-bengali block">সমবায় কর্মী, অনুমোদিত বিক্রেতা ও প্রশাসকদের জন্য।</span>
                </p>
            </div>
        </main>
    );
}

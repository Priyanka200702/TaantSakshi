import axios from "axios";

export const BACKEND = process.env.REACT_APP_BACKEND_URL || "";

export const api = axios.create({ baseURL: `${BACKEND}/api` });

const AUTH_KEY = "ts_auth_v1";

export const auth = {
    get() {
        try {
            return JSON.parse(localStorage.getItem(AUTH_KEY) || "null");
        } catch {
            return null;
        }
    },
    set(data) {
        localStorage.setItem(AUTH_KEY, JSON.stringify(data));
        window.dispatchEvent(new Event("ts-auth"));
    },
    clear() {
        localStorage.removeItem(AUTH_KEY);
        window.dispatchEvent(new Event("ts-auth"));
    },
};

api.interceptors.request.use((cfg) => {
    const a = auth.get();
    if (a?.token) cfg.headers.Authorization = `Bearer ${a.token}`;
    return cfg;
});

api.interceptors.response.use(
    (r) => r,
    (err) => {
        if (err?.response?.status === 401 && auth.get()) auth.clear();
        return Promise.reject(err);
    }
);

export const photoUrl = (u) => (u && !u.startsWith("http") ? `${BACKEND}${u}` : u);

export const apiErrorText = (err, lang = "en") => {
    const d = err?.response?.data;
    if (!d) return err?.message || "Something went wrong";
    return lang === "bn" ? d.message_bn || d.detail : d.message_en || d.detail;
};

export const isStaff = (user) => user && (user.role === "staff" || user.role === "admin");
export const canVerify = (user) => user && ["seller", "staff", "admin"].includes(user.role);

"use strict";

const DB_NAME = "tantsaakshi-local";
const CACHE_NAME = "tantsaakshi-app-shell-v6";
const APP_SHELL = ["/app", "/static/app.css", "/static/app.js"];

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
    event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key.startsWith("tantsaakshi-app-shell-") && key !== CACHE_NAME).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);
    if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
    if (url.pathname !== "/app" && !url.pathname.startsWith("/static/app.")) return;
    event.respondWith(caches.match(event.request).then((cached) => {
        if (cached) {
            event.waitUntil(fetch(event.request).then((response) => {
                if (response.ok) return caches.open(CACHE_NAME).then((cache) => cache.put(event.request, response.clone()));
                return undefined;
            }).catch(() => {}));
            return cached;
        }
        return fetch(event.request).then((response) => {
            if (response.ok) caches.open(CACHE_NAME).then((cache) => cache.put(event.request, response.clone()));
            return response;
        });
    }));
});

self.addEventListener("sync", (event) => {
    if (event.tag === "tantsaakshi-uploads") event.waitUntil(flushQueue());
});

self.addEventListener("message", (event) => {
    if (event.data?.type === "SYNC_UPLOADS") event.waitUntil(flushQueue());
});

function openDb() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open(DB_NAME, 1);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });
}

function readAll(db, storeName) {
    return new Promise((resolve, reject) => {
        const request = db.transaction(storeName, "readonly").objectStore(storeName).getAll();
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
    });
}

function readOne(db, storeName, key) {
    return new Promise((resolve, reject) => {
        const request = db.transaction(storeName, "readonly").objectStore(storeName).get(key);
        request.onsuccess = () => resolve(request.result || null);
        request.onerror = () => reject(request.error);
    });
}

function writeRecord(db, storeName, value) {
    return new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, "readwrite");
        tx.objectStore(storeName).put(value);
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error);
    });
}

function photoFilename(photo, qrId) {
    const extension = ({
        "image/png": "png",
        "image/heic": "heic",
        "image/heif": "heif",
        "image/jpeg": "jpg",
    })[photo.type?.toLowerCase()] || "jpg";
    return `${qrId}.${extension}`;
}

async function tellClients() {
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    clients.forEach((client) => client.postMessage({ type: "QUEUE_UPDATED" }));
}

async function flushQueue() {
    let db;
    try {
        db = await openDb();
        const auth = await readOne(db, "session", "current");
        if (!auth?.token) return;
        const captures = await readAll(db, "captures");
        for (const capture of captures.filter((item) => item.state === "waiting" || (item.state === "uploading" && Date.now() - Number(item.attemptedAt || 0) > 120000))) {
            await writeRecord(db, "captures", { ...capture, state: "uploading", attemptedAt: Date.now(), note: "" });
            await tellClients();
            const form = new FormData();
            form.append("qr_id", capture.qrId);
            form.append("batch_id", capture.batchId);
            form.append("upload_id", capture.uploadId);
            form.append("phone_model", capture.phoneModel || "");
            form.append("photos", capture.photo, photoFilename(capture.photo, capture.qrId));
            try {
                const response = await fetch("/saree", { method: "POST", headers: { Authorization: `Bearer ${auth.token}` }, body: form });
                if (response.ok) {
                    const payload = await response.json().catch(() => ({}));
                    await writeRecord(db, "captures", { ...capture, state: "sent", serverStatus: payload.status || "queued", sentAt: Date.now(), note: "" });
                } else {
                    const payload = await response.json().catch(() => ({}));
                    const message = [payload.message_bn, payload.message_en, payload.detail].filter(Boolean).join(" · ") || `Upload failed (${response.status})`;
                    await writeRecord(db, "captures", { ...capture, state: response.status >= 500 ? "waiting" : "failed", note: message });
                    if (response.status === 401) break;
                }
            } catch {
                await writeRecord(db, "captures", { ...capture, state: "waiting", note: "ইন্টারনেট সংযোগ নেই · No connection to the server" });
                break;
            }
            await tellClients();
        }
    } catch (error) {
        console.warn("Background upload sync paused", error);
    } finally {
        db?.close();
    }
}

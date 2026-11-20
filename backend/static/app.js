(() => {
    "use strict";

    const DB_NAME = "tantsaakshi-local";
    const DB_VERSION = 1;
    const SESSION_KEY = "tantsaakshi-session";
    const QUALITY_FAILURE_CODES = new Set(["NO_CARD", "TOO_TILTED", "LOW_RES", "TOO_DARK", "GLARE", "BLURRY", "NO_WEAVE", "ALIASING", "WEAVE_UNCLEAR", "DESIGN_AREA", "BAD_IMAGE"]);
    const API_BASE = (window.TANTSAAKSHI_API_URL || "").replace(/\/$/, "");
    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
    const hasBengali = /[\u0980-\u09FF]/;
    const hasLatin = /[A-Za-z]/;
    const bilingualScopes = "p,button,label,h1,h2,h3,h4,small,strong,em,li,a,span";

    function bilingualScopeFor(element) {
        for (let current = element; current && !current.matches("body,main,section,.app-frame"); current = current.parentElement) {
            if (!current.matches(bilingualScopes)) continue;
            const text = current.textContent || "";
            if (hasBengali.test(text) && hasLatin.test(text)) return current;
        }
        return null;
    }

    function annotateBilingualTextNode(node) {
        const parent = node.parentElement;
        const text = node.nodeValue || "";
        if (!parent || !text.trim() || parent.closest(".bn,.en,script,style,noscript,textarea,option,[aria-hidden='true'],[contenteditable='true'],.brand-copy,.user-chip,.title-name,.batch-id,.stamp-number")) return;
        if (!bilingualScopeFor(parent)) return;

        const parts = text.match(/[\u0980-\u09FF]+|[^\u0980-\u09FF]+/g) || [];
        if (!parts.some((part) => hasBengali.test(part) || hasLatin.test(part))) return;
        const fragment = document.createDocumentFragment();
        for (const part of parts) {
            const language = hasBengali.test(part) ? "bn" : hasLatin.test(part) ? "en" : "";
            if (!language) {
                fragment.append(document.createTextNode(part));
                continue;
            }
            const span = document.createElement("span");
            span.className = language;
            span.textContent = part;
            fragment.append(span);
        }
        node.replaceWith(fragment);
    }

    function annotateBilingualText(root) {
        if (root.nodeType === Node.TEXT_NODE) {
            annotateBilingualTextNode(root);
            return;
        }
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(annotateBilingualTextNode);
    }

    function setLanguageMode(mode) {
        const language = mode === "en" ? "en" : "bn";
        const switchTo = language === "bn" ? "English" : "Bangla";
        document.documentElement.lang = language;
        document.body.dataset.langFirst = language;
        const toggle = $("#language-toggle");
        toggle.setAttribute("aria-label", `${language === "bn" ? "Bangla" : "English"} mode selected. Switch to ${switchTo}.`);
        toggle.title = `${language === "bn" ? "Bangla" : "English"} mode selected`;
        localStorage.setItem("tantsaakshi-language-order", language);
    }

    function watchBilingualText() {
        annotateBilingualText(document.body);
        const observer = new MutationObserver((records) => {
            for (const record of records) {
                for (const node of record.addedNodes) annotateBilingualText(node);
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    let dbPromise;
    let session = null;
    let activeScreen = "login";
    let activeBatch = null;
    let mediaStream = null;
    let mediaMode = null;
    let qrDetector = null;
    let scanTimer = 0;
    let qualityTimer = 0;
    let lastAutoCaptureAt = 0;
    let captureBusy = false;
    let currentCaptureQr = "";
    let currentVerifyQr = "";
    let currentSharpness = 0;
    let currentGlare = 0;
    let toastTimer = 0;
    let captureSuccessTimer = 0;
    const batchQrIds = new Set();

    function openDb() {
        if (dbPromise) return dbPromise;
        dbPromise = new Promise((resolve, reject) => {
            if (!("indexedDB" in window)) {
                reject(new Error("This browser cannot store the offline upload queue."));
                return;
            }
            const request = indexedDB.open(DB_NAME, DB_VERSION);
            request.onupgradeneeded = () => {
                const db = request.result;
                if (!db.objectStoreNames.contains("captures")) db.createObjectStore("captures", { keyPath: "uploadId" });
                if (!db.objectStoreNames.contains("session")) db.createObjectStore("session", { keyPath: "key" });
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error || new Error("Could not open offline storage."));
        });
        return dbPromise;
    }

    async function storeRecord(storeName, record) {
        const db = await openDb();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(storeName, "readwrite");
            tx.objectStore(storeName).put(record);
            tx.oncomplete = () => resolve(record);
            tx.onerror = () => reject(tx.error || new Error("Could not save this item."));
        });
    }

    async function getRecord(storeName, key) {
        const db = await openDb();
        return new Promise((resolve, reject) => {
            const request = db.transaction(storeName, "readonly").objectStore(storeName).get(key);
            request.onsuccess = () => resolve(request.result || null);
            request.onerror = () => reject(request.error || new Error("Could not read saved data."));
        });
    }

    async function getCaptures() {
        const db = await openDb();
        return new Promise((resolve, reject) => {
            const request = db.transaction("captures", "readonly").objectStore("captures").getAll();
            request.onsuccess = () => resolve(request.result.sort((a, b) => b.createdAt - a.createdAt));
            request.onerror = () => reject(request.error || new Error("Could not read the upload queue."));
        });
    }

    async function updateCapture(uploadId, changes) {
        const existing = await getRecord("captures", uploadId);
        if (!existing) return null;
        return storeRecord("captures", { ...existing, ...changes });
    }

    function getStoredSession() {
        try { return JSON.parse(localStorage.getItem(SESSION_KEY) || "null"); }
        catch { return null; }
    }

    async function saveSession(value) {
        session = value;
        localStorage.setItem(SESSION_KEY, JSON.stringify(value));
        try { await storeRecord("session", { key: "current", token: value.token }); } catch { /* foreground queue remains available */ }
        updateUserChip();
    }

    async function clearSession() {
        session = null;
        activeBatch = null;
        localStorage.removeItem(SESSION_KEY);
        try {
            const db = await openDb();
            await new Promise((resolve) => {
                const tx = db.transaction("session", "readwrite");
                tx.objectStore("session").delete("current");
                tx.oncomplete = resolve;
                tx.onerror = resolve;
            });
        } catch { /* nothing else to clear */ }
        stopCamera();
        setScreen("login");
        updateUserChip();
        showToast("লগ আউট হয়েছে · You are signed out");
    }

    class ApiError extends Error {
        constructor(message, status, payload) {
            super(message);
            this.name = "ApiError";
            this.status = status;
            this.payload = payload;
        }
    }

    async function api(path, options = {}) {
        const headers = new Headers(options.headers || {});
        if (session?.token) headers.set("Authorization", `Bearer ${session.token}`);
        if (options.json !== undefined) headers.set("Content-Type", "application/json");
        let response;
        try {
            response = await fetch(`${API_BASE}${path}`, {
                method: options.method || (options.json === undefined ? "GET" : "POST"),
                headers,
                body: options.json === undefined ? options.body : JSON.stringify(options.json),
                signal: options.signal,
            });
        } catch (error) {
            throw new ApiError("ইন্টারনেট সংযোগ নেই · No connection to the server", 0, error);
        }
        const type = response.headers.get("content-type") || "";
        const payload = type.includes("application/json") ? await response.json().catch(() => ({})) : await response.text().catch(() => "");
        if (!response.ok) {
            const message = typeof payload === "object"
                ? [payload.message_bn, payload.message_en, payload.detail].filter(Boolean).join(" · ")
                : payload;
            throw new ApiError(message || `Request failed (${response.status})`, response.status, payload);
        }
        return payload;
    }

    function setScreen(name) {
        const previousScreen = activeScreen;
        if (previousScreen === "summary" && name === "home") {
            activeBatch = null;
            batchQrIds.clear();
            localStorage.removeItem("tantsaakshi-active-batch");
        }
        if (activeScreen === "capture" && name !== "capture") stopCamera();
        if (activeScreen === "verify" && name !== "verify") stopCamera();
        activeScreen = name;
        $$("[data-screen]").forEach((screen) => {
            const active = screen.dataset.screen === name;
            screen.classList.toggle("is-active", active);
            screen.hidden = !active;
        });
        $("#bottom-nav").hidden = name === "login" || !session;
        $$('[data-nav]').forEach((button) => {
            const target = button.dataset.nav;
            button.classList.toggle("is-current", target === name || (target === "batch" && name === "capture"));
        });
        window.scrollTo({ top: 0, behavior: "smooth" });
        if (name === "home") refreshHome();
        if (name === "uploads") renderQueue();
        if (name === "capture") refreshCaptureHeader();
        if (name === "summary") renderSummary();
        if (name === "verify") resetVerifyResult();
    }

    function updateUserChip() {
        const chip = $("#user-chip");
        chip.hidden = !session;
        if (!session) return;
        $("#user-name").textContent = session.name || "TantSaakshi";
        $("#user-avatar").textContent = (session.name || "T").trim().slice(0, 1);
        const isSeller = session.role === "seller";
        $$('[data-action="new-batch"], [data-nav="batch"]').forEach((button) => { button.hidden = isSeller; });
    }

    function showToast(message, isError = false) {
        const toast = $("#toast");
        toast.textContent = message;
        toast.classList.toggle("is-error", isError);
        toast.classList.add("is-visible");
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 3400);
        $("#live-region").textContent = message;
    }

    function setError(element, message) {
        element.textContent = message;
        element.hidden = !message;
    }

    function formatTime(timestamp) {
        return new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit" }).format(new Date(timestamp));
    }

    function createId() {
        if (window.crypto?.randomUUID) return window.crypto.randomUUID();
        return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
            const random = Math.random() * 16 | 0;
            return (char === "x" ? random : (random & 3 | 8)).toString(16);
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

    function latestPerQr(records) {
        const latest = new Map();
        [...records].sort((a, b) => b.createdAt - a.createdAt).forEach((record) => {
            if (!latest.has(record.qrId)) latest.set(record.qrId, record);
        });
        return [...latest.values()];
    }

    function needsRetake(record) {
        return record?.serverStatus === "failed" && QUALITY_FAILURE_CODES.has(record.serverCode);
    }

    function pendingCount(records) {
        return latestPerQr(records).filter((record) => record.state !== "sent" || record.serverStatus === "failed").length;
    }

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
    }

    function updateNetworkState() {
        const online = navigator.onLine;
        const pill = $("#network-pill");
        pill.classList.toggle("is-offline", !online);
        $("#network-label").textContent = online ? "অনলাইন · Online" : "অফলাইন · Offline";
        if (online) {
            syncQueue();
            refreshServerStatuses();
        }
    }

    async function refreshHome() {
        if (session) $("#welcome-name").textContent = `, ${session.name || ""}`;
        const resumeCard = $("#resume-batch");
        resumeCard.hidden = !activeBatch || session?.role === "seller";
        if (activeBatch) $("#resume-batch-name").textContent = `${activeBatch.sareeType} · ${activeBatch.weaverName}`;
        const now = new Date();
        $("#home-title .en").textContent = now.getHours() < 12 ? "Good morning" : now.getHours() < 17 ? "Good afternoon" : "Good evening";
        const date = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short" }).format(now);
        $("#home-date").textContent = `আজ · TODAY  /  ${date.toUpperCase()}`;
        try {
            const records = await getCaptures();
            const today = new Date().toDateString();
            const todayCount = records.filter((item) => new Date(item.createdAt).toDateString() === today).length;
            const pending = pendingCount(records);
            $("#home-registered").textContent = String(todayCount).padStart(2, "0");
            $("#pending-copy").textContent = pending;
            $("#pending-copy-en").textContent = `${pending} pending`;
            $("#nav-pending-dot").hidden = pending === 0;
        } catch (error) {
            console.warn("Local queue unavailable", error);
        }
    }

    async function loadWeavers() {
        if (!session || session.role === "seller") return;
        const select = $("#weaver");
        try {
            const weavers = await api("/weavers");
            select.innerHTML = '<option value="">তাঁতশিল্পী বেছে নিন · Choose a weaver</option>';
            weavers.forEach((weaver) => {
                const option = document.createElement("option");
                option.value = weaver.id;
                option.textContent = weaver.name;
                option.dataset.name = weaver.name;
                select.append(option);
            });
            if (!weavers.length) showToast("তাঁতশিল্পীর তালিকা খালি · No weavers found", true);
        } catch (error) {
            if (error.status === 401) clearSession();
            setError($("#batch-error"), error.message);
        }
    }

    async function enterApp(value) {
        await saveSession(value);
        updateUserChip();
        await loadWeavers();
        setScreen("home");
        await renderQueue();
        setupServiceWorker();
        syncQueue();
    }

    function setupServiceWorker() {
        if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
        navigator.serviceWorker.register("/service-worker.js").then((registration) => {
            if (registration.sync) registration.sync.register("tantsaakshi-uploads").catch(() => {});
        }).catch(() => {});
    }

    function showPin() {
        const input = $("#pin");
        input.type = input.type === "password" ? "text" : "password";
        $("#show-pin").textContent = input.type === "password" ? "দেখুন · Show" : "লুকান · Hide";
    }

    function startNewBatch() {
        if (!session || session.role === "seller") return;
        setError($("#batch-error"), "");
        setScreen("batch");
        loadWeavers();
    }

    async function submitBatch(event) {
        event.preventDefault();
        const errorBox = $("#batch-error");
        setError(errorBox, "");
        const weaverSelect = $("#weaver");
        const type = $("#saree-type").value.trim();
        if (!weaverSelect.value || !type) {
            setError(errorBox, "তাঁতশিল্পী ও শাড়ির ধরন বেছে নিন · Choose a weaver and saree variety");
            return;
        }
        const submit = $("#batch-form button[type='submit']");
        submit.disabled = true;
        try {
            if (!navigator.onLine) throw new ApiError("ব্যাচ শুরু করতে ইন্টারনেট দরকার · Connect to start a batch", 0);
            const response = await api("/batch", { json: { weaver_id: weaverSelect.value, saree_type: type } });
            activeBatch = {
                id: response.batch_id,
                weaverId: weaverSelect.value,
                weaverName: weaverSelect.selectedOptions[0]?.textContent || "",
                sareeType: type,
                startedBy: session?.name || "",
                coopId: session?.coop_id || null,
                startedAt: Date.now(),
            };
            batchQrIds.clear();
            try { localStorage.setItem("tantsaakshi-active-batch", JSON.stringify(activeBatch)); } catch { /* batch is active in memory */ }
            refreshCaptureHeader();
            setScreen("capture");
        } catch (error) {
            if (error.status === 401) clearSession();
            setError(errorBox, error.message);
        } finally {
            submit.disabled = false;
        }
    }

    function refreshCaptureHeader() {
        if (activeBatch) {
            $("#capture-batch-label").textContent = activeBatch.sareeType.toUpperCase();
            $("#capture-count").textContent = String(batchQrIds.size + 1).padStart(2, "0");
        }
    }

    async function resumeBatch() {
        if (!activeBatch) return;
        try {
            const captures = await getCaptures();
            latestPerQr(captures.filter((item) => item.batchId === activeBatch.id))
                .filter((item) => !needsRetake(item))
                .forEach((item) => batchQrIds.add(item.qrId));
        } catch { /* the batch can still be resumed if the local queue cannot be read */ }
        currentCaptureQr = "";
        $("#capture-success").hidden = true;
        refreshCaptureHeader();
        setScreen("capture");
        showToast("ব্যাচ চালু · Batch resumed. Start the camera to continue.");
    }

    async function retakeCapture(uploadId) {
        if (!session || session.role === "seller") return showToast("নিবন্ধনের জন্য স্টাফ লগ ইন দরকার · Staff sign-in is required to retake", true);
        try {
            const failed = await getRecord("captures", uploadId);
            if (!needsRetake(failed)) return;
            activeBatch = {
                id: failed.batchId,
                weaverName: failed.weaverName,
                sareeType: failed.sareeType,
                startedBy: session.name || "",
                coopId: session.coop_id || null,
                startedAt: failed.createdAt,
            };
            localStorage.setItem("tantsaakshi-active-batch", JSON.stringify(activeBatch));
            const captures = await getCaptures();
            batchQrIds.clear();
            latestPerQr(captures.filter((item) => item.batchId === failed.batchId))
                .filter((item) => item.qrId !== failed.qrId && !needsRetake(item))
                .forEach((item) => batchQrIds.add(item.qrId));
            currentCaptureQr = "";
            $("#capture-success").hidden = true;
            refreshCaptureHeader();
            setScreen("capture");
            const reason = failed.serverReasonBn && failed.serverReason ? `${failed.serverReasonBn} · ${failed.serverReason}` : failed.serverReason || "ছবির গুণমান ঠিক করে আবার তুলুন · Improve the photo and try again";
            showToast(`ট্যাগ ${failed.qrId} আবার তুলুন · Retake ${failed.qrId}: ${reason}`);
        } catch (error) {
            showToast(error.message || "রিটেক শুরু করা যায়নি · Could not start the retake", true);
        }
    }

    function parseQrId(rawValue) {
        const raw = String(rawValue || "").trim();
        if (!raw) return "";
        try {
            const url = new URL(raw);
            const match = url.pathname.match(/\/c\/([^/]+)/i);
            if (match) return decodeURIComponent(match[1]).trim().toUpperCase();
        } catch { /* it is likely a plain tag ID */ }
        const pathMatch = raw.match(/(?:^|\/)c\/([^/?#]+)/i);
        return (pathMatch ? decodeURIComponent(pathMatch[1]) : raw).trim().toUpperCase();
    }

    async function startCamera(mode) {
        if (mode === "capture" && activeScreen !== "capture") return;
        if (mode === "verify" && activeScreen !== "verify") return;
        if (!navigator.mediaDevices?.getUserMedia) {
            showToast("এই ব্রাউজারে ক্যামেরা নেই · Camera access is not available", true);
            if (mode === "capture") $("#capture-file").click();
            else $("#verify-file").click();
            return;
        }
        if (!window.isSecureContext) {
            showToast("ক্যামেরার জন্য HTTPS বা localhost দরকার · Camera needs HTTPS or localhost", true);
            return;
        }
        stopCamera();
        const button = mode === "capture" ? $("#start-capture-camera") : $("#start-verify-camera");
        button.disabled = true;
        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: false,
                video: {
                    facingMode: { ideal: "environment" },
                    width: { ideal: 2560 },
                    height: { ideal: 1440 },
                },
            });
            mediaMode = mode;
            const video = mode === "capture" ? $("#capture-video") : $("#verify-video");
            video.srcObject = mediaStream;
            await video.play();
            const view = video.closest(mode === "capture" ? ".camera-view" : ".verify-camera-view");
            view.classList.add("is-live");
            if (mode === "capture") {
                $("#capture-camera-empty").hidden = true;
                $("#capture-camera-overlay").hidden = false;
                $("#camera-bottom-hint").hidden = false;
                const track = mediaStream.getVideoTracks()[0];
                const capabilities = track.getCapabilities?.() || {};
                $("#torch-button").disabled = !capabilities.torch;
                const focus = capabilities.focusMode?.includes("continuous") ? { focusMode: "continuous" } : null;
                if (focus) track.applyConstraints({ advanced: [focus] }).catch(() => {});
                initializeQrDetector();
                scanCamera(mode);
                qualityTimer = window.setInterval(sampleFrameQuality, 650);
            } else {
                $("#verify-camera-empty").hidden = true;
                $("#verify-camera-outline").hidden = false;
                initializeQrDetector();
                scanCamera(mode);
            }
        } catch (error) {
            showToast("ক্যামেরা চালু হয়নি · Could not start the camera. Check permission and try again.", true);
            console.warn("Camera start failed", error);
        } finally {
            button.disabled = false;
        }
    }

    function stopCamera() {
        window.clearTimeout(scanTimer);
        window.clearInterval(qualityTimer);
        if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
        mediaStream = null;
        mediaMode = null;
        qrDetector = null;
        ["#capture-video", "#verify-video"].forEach((selector) => {
            const video = $(selector);
            if (video) {
                video.pause();
                video.srcObject = null;
                video.closest(".camera-view, .verify-camera-view")?.classList.remove("is-live");
            }
        });
        $("#capture-camera-empty").hidden = false;
        $("#capture-camera-overlay").hidden = true;
        $("#camera-bottom-hint").hidden = true;
        $("#verify-camera-empty").hidden = false;
        $("#verify-camera-outline").hidden = true;
        $("#torch-button").disabled = true;
        $("#capture-now").disabled = true;
    }

    async function initializeQrDetector() {
        if (!("BarcodeDetector" in window)) {
            qrDetector = null;
            return;
        }
        try {
            const formats = await window.BarcodeDetector.getSupportedFormats();
            if (formats.includes("qr_code")) qrDetector = new window.BarcodeDetector({ formats: ["qr_code"] });
        } catch { qrDetector = null; }
    }

    async function scanCamera(mode) {
        const video = mode === "capture" ? $("#capture-video") : $("#verify-video");
        if (!mediaStream || mediaMode !== mode || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
            scanTimer = window.setTimeout(() => scanCamera(mode), 350);
            return;
        }
        if (qrDetector) {
            try {
                const codes = await qrDetector.detect(video);
                const candidate = codes.find((code) => code.rawValue)?.rawValue;
                if (candidate) {
                    const id = parseQrId(candidate);
                    if (mode === "capture") onCaptureQr(id);
                    else onVerifyQr(id);
                }
            } catch { /* keep the live preview running if this frame cannot be decoded */ }
        }
        scanTimer = window.setTimeout(() => scanCamera(mode), 300);
    }

    function onCaptureQr(id) {
        if (!id || currentCaptureQr === id) return;
        if (batchQrIds.has(id)) {
            $("#scanned-qr-id").textContent = `${id} · already captured`;
            $("#qr-status-description").innerHTML = "এই ব্যাচে এই ট্যাগ নেওয়া হয়েছে।<br>This tag is already in this batch.";
            return;
        }
        currentCaptureQr = id;
        $("#scanned-qr-id").textContent = id;
        $("#qr-status-description").innerHTML = "QR পড়া হয়েছে · QR ID read successfully.";
        $("#qr-status-dot").classList.add("is-found");
        $("#step-qr-check").textContent = "✓";
        $("#capture-now").disabled = false;
        maybeAutoCapture();
    }

    function onVerifyQr(id) {
        if (!id || currentVerifyQr === id) return;
        currentVerifyQr = id;
        $("#verify-qr-id").textContent = id;
        $("#verify-capture").disabled = false;
        showToast("ট্যাগ পড়া হয়েছে · Tag read. Take a weave photo.");
    }

    function setQualityHint(kind, message) {
        const light = $("#quality-light");
        light.classList.toggle("is-good", kind === "good");
        light.classList.toggle("is-warn", kind === "warn");
        $("#quality-hint").textContent = message;
    }

    function sampleFrameQuality() {
        if (!mediaStream || mediaMode !== "capture") return;
        const video = $("#capture-video");
        if (!video.videoWidth || !video.videoHeight) return;
        const canvas = $("#scan-canvas");
        const width = 128, height = 96;
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        context.drawImage(video, 0, 0, width, height);
        const image = context.getImageData(0, 0, width, height).data;
        const gray = new Uint8Array(width * height);
        let white = 0;
        for (let i = 0, pixel = 0; i < image.length; i += 4, pixel += 1) {
            const value = image[i] * .299 + image[i + 1] * .587 + image[i + 2] * .114;
            gray[pixel] = value;
            if (value > 248) white += 1;
        }
        let sum = 0, sumSquares = 0, count = 0;
        for (let y = 1; y < height - 1; y += 1) {
            for (let x = 1; x < width - 1; x += 1) {
                const i = y * width + x;
                const laplacian = 4 * gray[i] - gray[i - 1] - gray[i + 1] - gray[i - width] - gray[i + width];
                sum += laplacian;
                sumSquares += laplacian * laplacian;
                count += 1;
            }
        }
        currentSharpness = sumSquares / count - (sum / count) ** 2;
        currentGlare = white / (width * height);
        const qualityStep = $("#sharpness-step");
        if (currentGlare > .11) {
            setQualityHint("warn", "আলো ঝলকাচ্ছে · Glare detected — tilt the phone a little");
            qualityStep.classList.remove("is-complete");
        } else if (currentSharpness < 20) {
            setQualityHint("warn", "ফোন স্থির রাখুন · Hold steady while it focuses");
            qualityStep.classList.remove("is-complete");
        } else {
            setQualityHint("good", "পরিষ্কার ছবি · Sharp enough — hold for a moment");
            qualityStep.classList.add("is-complete");
            $("#sharpness-check").textContent = "✓";
            maybeAutoCapture();
        }
    }

    function maybeAutoCapture() {
        if (!currentCaptureQr || !mediaStream || mediaMode !== "capture" || captureBusy || currentSharpness < 20 || currentGlare > .11) return;
        const now = Date.now();
        if (now - lastAutoCaptureAt < 1400) return;
        lastAutoCaptureAt = now;
        captureCurrentPhoto(false);
    }

    async function toggleTorch() {
        const track = mediaStream?.getVideoTracks()[0];
        if (!track) return;
        const capabilities = track.getCapabilities?.() || {};
        if (!capabilities.torch) return showToast("এই ফোনে টর্চ কন্ট্রোল নেই · Torch control isn’t available on this phone");
        const next = !track.getSettings?.().torch;
        try {
            await track.applyConstraints({ advanced: [{ torch: next }] });
            $("#torch-button").classList.toggle("is-on", next);
        } catch {
            showToast("টর্চ চালু হয়নি · Could not change torch setting", true);
        }
    }

    function beepAndBuzz() {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) {
                const context = new AudioContext();
                const oscillator = context.createOscillator();
                const gain = context.createGain();
                oscillator.frequency.value = 880;
                gain.gain.value = .045;
                oscillator.connect(gain);
                gain.connect(context.destination);
                oscillator.start();
                oscillator.stop(context.currentTime + .1);
                oscillator.onended = () => context.close();
            }
        } catch { /* vibration is still helpful on supported phones */ }
        if (navigator.vibrate) navigator.vibrate([45, 40, 45]);
    }

    async function captureCurrentPhoto(fromFileInput = false, file = null) {
        if (captureBusy) return;
        if (!currentCaptureQr) {
            showToast("আগে QR ট্যাগ স্ক্যান করুন · Scan the QR tag first", true);
            return;
        }
        captureBusy = true;
        $("#capture-now").disabled = true;
        let photo = file;
        try {
            if (!photo && !fromFileInput) {
                const track = mediaStream?.getVideoTracks()[0];
                if (track && "ImageCapture" in window) {
                    try { photo = await new window.ImageCapture(track).takePhoto(); }
                    catch (error) { console.info("Full-resolution capture fallback", error); }
                }
            }
            if (!photo && !fromFileInput) {
                captureBusy = false;
                $("#capture-file").click();
                return;
            }
            if (!photo || !photo.size) throw new Error("ছবিটি পড়া যায়নি · Could not read the photo. Try again.");
            if (photo.size > 25 * 1024 * 1024) throw new Error("ছবিটি ২৫ MB-এর বেশি · This photo is over 25 MB. Capture a smaller image.");
            const uploadId = createId();
            const capture = {
                uploadId,
                qrId: currentCaptureQr,
                batchId: activeBatch?.id,
                weaverName: activeBatch?.weaverName || "",
                sareeType: activeBatch?.sareeType || "",
                phoneModel: (navigator.userAgent || "").slice(0, 120),
                photo,
                createdAt: Date.now(),
                state: "waiting",
                note: "",
            };
            await storeRecord("captures", capture);
            batchQrIds.add(currentCaptureQr);
            currentCaptureQr = "";
            $("#capture-success").hidden = false;
            window.clearTimeout(captureSuccessTimer);
            captureSuccessTimer = window.setTimeout(() => { $("#capture-success").hidden = true; }, 1200);
            $("#scanned-qr-id").textContent = "পরের ট্যাগের অপেক্ষায় · Ready for next tag";
            $("#qr-status-description").innerHTML = "পরের শাড়ির QR ট্যাগটি দেখান।<br>Hold up the next saree’s QR tag.";
            $("#qr-status-dot").classList.remove("is-found");
            $("#step-qr-check").textContent = "•";
            $("#capture-now").disabled = true;
            $("#capture-count").textContent = String(batchQrIds.size + 1).padStart(2, "0");
            $("#sharpness-step").classList.remove("is-complete");
            $("#sharpness-check").textContent = "•";
            currentSharpness = 0;
            beepAndBuzz();
            showToast("সেভ হয়েছে · Saved on this phone");
            renderQueue();
            requestWorkerSync();
            syncQueue();
        } catch (error) {
            showToast(error.message || "ছবি সেভ হয়নি · Could not save this photo", true);
        } finally {
            captureBusy = false;
            if (currentCaptureQr) $("#capture-now").disabled = false;
        }
    }

    function requestWorkerSync() {
        if (!("serviceWorker" in navigator) || !window.isSecureContext) return;
        navigator.serviceWorker.ready.then((registration) => {
            if (registration.sync) registration.sync.register("tantsaakshi-uploads").catch(() => {});
            registration.active?.postMessage({ type: "SYNC_UPLOADS" });
        }).catch(() => {});
    }

    let syncRunning = false;
    async function syncQueue(retryFailed = false) {
        if (syncRunning || !session?.token || !navigator.onLine) return;
        syncRunning = true;
        try {
            const records = (await getCaptures()).filter((item) => item.state === "waiting" || (item.state === "uploading" && Date.now() - Number(item.attemptedAt || 0) > 120000) || (retryFailed && item.state === "failed"));
            for (const record of records) {
                if (!navigator.onLine) break;
                await updateCapture(record.uploadId, { state: "uploading", attemptedAt: Date.now(), note: "" });
                if (activeScreen === "uploads") renderQueue();
                const data = new FormData();
                data.append("qr_id", record.qrId);
                data.append("batch_id", record.batchId);
                data.append("upload_id", record.uploadId);
                data.append("phone_model", record.phoneModel || "");
                data.append("photos", record.photo, photoFilename(record.photo, record.qrId));
                try {
                    const response = await api("/saree", { method: "POST", body: data });
                    await updateCapture(record.uploadId, { state: "sent", serverStatus: response.status || "queued", sentAt: Date.now(), note: "" });
                } catch (error) {
                    const transient = error.status === 0 || error.status >= 500;
                    await updateCapture(record.uploadId, { state: transient ? "waiting" : "failed", note: error.message });
                    if (error.status === 401) {
                        showToast("আবার লগ ইন করুন · Please sign in again to resume uploads", true);
                        break;
                    }
                }
                if (activeScreen === "uploads") renderQueue();
            }
        } catch (error) {
            console.warn("Upload queue sync paused", error);
        } finally {
            syncRunning = false;
            renderQueue();
            refreshServerStatuses();
        }
    }

    let statusRefreshRunning = false;
    async function refreshServerStatuses() {
        if (statusRefreshRunning || !session?.token || !navigator.onLine) return;
        statusRefreshRunning = true;
        let changed = false;
        try {
            const records = (await getCaptures()).filter((item) => item.state === "sent" && ["queued", "processing"].includes(item.serverStatus));
            for (const record of records.slice(0, 12)) {
                try {
                    const status = await api(`/saree/${encodeURIComponent(record.qrId)}`);
                    await updateCapture(record.uploadId, {
                        serverStatus: status.status,
                        serverCode: status.code || "",
                        serverReason: status.reason || "",
                        serverReasonBn: status.reason_bn || "",
                        grade: status.grade || "",
                        endsPerInch: status.ends_per_inch ?? null,
                        picksPerInch: status.picks_per_inch ?? null,
                        statusCheckedAt: Date.now(),
                    });
                    changed = true;
                } catch (error) {
                    if (error.status === 401) {
                        showToast("আবার লগ ইন করুন · Please sign in again to check analysis", true);
                        break;
                    }
                }
            }
        } catch (error) {
            console.warn("Processing status check paused", error);
        } finally {
            statusRefreshRunning = false;
            if (changed) {
                renderQueue();
                if (activeScreen === "home") refreshHome();
                if (activeScreen === "summary") renderSummary();
            }
        }
    }

    async function renderQueue() {
        try {
            const records = await getCaptures();
            const pending = pendingCount(records);
            $("#queue-pending-count").textContent = String(pending);
            $("#pending-copy").textContent = String(pending);
            $("#pending-copy-en").textContent = `${pending} pending`;
            $("#nav-pending-dot").hidden = pending === 0;
            const list = $("#upload-list");
            const empty = $("#queue-empty");
            empty.hidden = records.length !== 0;
            list.hidden = records.length === 0;
            list.replaceChildren();
            const latestIds = new Set(latestPerQr(records).map((item) => item.uploadId));
            records.slice(0, 40).forEach((record) => {
                const row = document.createElement("article");
                row.className = "upload-item";
                const retake = latestIds.has(record.uploadId) && needsRetake(record);
                const serverFailed = record.state === "sent" && record.serverStatus === "failed";
                const serverDone = record.state === "sent" && record.serverStatus === "done";
                const serverProcessing = record.state === "sent" && ["queued", "processing"].includes(record.serverStatus);
                const status = record.state !== "sent" ? record.state === "failed" ? "failed" : record.state === "uploading" ? "sending" : "waiting" : retake ? "retake" : serverFailed ? "failed" : serverDone ? "done" : serverProcessing ? "analyzing" : "sent";
                const statusLabel = ({ sent: "✓ পাঠানো · sent", done: "✓ সম্পূর্ণ · done", analyzing: "⟳ বিশ্লেষণ · analyzing", retake: "↻ রিটেক · retake", failed: "✕ ব্যর্থ · failed", sending: "⟳ পাঠানো হচ্ছে · sending", waiting: "⟳ অপেক্ষা · waiting" })[status];
                const analysisDetail = serverDone ? `${record.grade ? `Grade ${record.grade} · ` : ""}বিশ্লেষণ সম্পূর্ণ · Analysis complete` : serverProcessing ? "বিশ্লেষণ চলছে · Analysis in progress" : retake ? `${record.serverReasonBn || record.serverReason || "আবার ছবি তুলুন · Please retake this photo"}` : serverFailed ? `${record.serverReasonBn || record.serverReason || "সমস্যা হয়েছে · Analysis needs attention"}` : "বিশ্লেষণের অপেক্ষায় · Analysis queued";
                const subtitle = record.state === "sent" ? analysisDetail : record.note || (record.state === "failed" ? "আবার চেষ্টা করুন · Try again" : "নেটওয়ার্কের অপেক্ষায় · Waiting for connection");
                const retryButton = record.state === "failed" ? `<button class="upload-retry" type="button" data-retry="${escapeHtml(record.uploadId)}">আবার · Retry</button>` : retake ? `<button class="upload-retry" type="button" data-retake="${escapeHtml(record.uploadId)}">রিটেক · Retake</button>` : "";
                row.innerHTML = `<span class="upload-thumb" aria-hidden="true">▧</span><span class="upload-copy"><strong>${escapeHtml(record.qrId)}</strong><small>${escapeHtml(record.sareeType || "Handloom saree")} · ${escapeHtml(formatTime(record.createdAt))} · ${escapeHtml(subtitle)}</small></span><span class="upload-status status-${status}"><i class="status-check">${["sent", "done"].includes(status) ? "✓" : ["failed", "retake"].includes(status) ? "!" : "·"}</i>${statusLabel}</span>${retryButton}`;
                list.append(row);
            });
        } catch (error) {
            console.warn("Could not render queue", error);
        }
    }

    async function renderSummary() {
        if (!activeBatch) return;
        $("#summary-weaver").textContent = activeBatch.weaverName || "—";
        $("#summary-variety").textContent = activeBatch.sareeType || "—";
        $("#summary-batch-id").textContent = activeBatch.id || "—";
        try {
            const all = await getCaptures();
            const captures = latestPerQr(all.filter((item) => item.batchId === activeBatch.id)).sort((a, b) => a.createdAt - b.createdAt);
            const pendingUploads = captures.filter((item) => item.state !== "sent").length;
            const retakes = captures.filter(needsRetake).length;
            $("#summary-count").textContent = String(captures.length);
            $("#summary-upload-state").textContent = retakes ? `${retakes} photo retake(s) · আবার তুলুন` : pendingUploads ? `${pendingUploads} pending · বাকি` : "সব পাঠানো হয়েছে · All sent";
            $("#summary-captures").innerHTML = captures.slice(-8).reverse().map((item) => `<div class="summary-item"><span class="summary-thumb">▧</span><span class="summary-item-copy"><strong>${escapeHtml(item.qrId)}</strong><small>${escapeHtml(formatTime(item.createdAt))} · ${escapeHtml(item.sareeType)}</small></span><span class="summary-item-state">${needsRetake(item) ? "↻ retake" : item.serverStatus === "done" ? "✓ done" : item.state === "sent" ? "✓ sent" : "⟳ waiting"}</span></div>`).join("") || '<div class="summary-item"><span class="summary-item-copy"><small>এখনও ছবি তোলা হয়নি · No sarees captured yet</small></span></div>';
        } catch { /* summary remains useful without local queue access */ }
    }

    function finishBatch() {
        if (!batchQrIds.size) {
            showToast("এই ব্যাচে অন্তত একটি ছবি তুলুন · Capture at least one saree in this batch", true);
            return;
        }
        setScreen("summary");
    }

    function resetVerifyResult() {
        const card = $("#verify-result");
        card.className = "verify-result-card";
        card.innerHTML = '<span class="result-seal">?</span><p class="eyebrow">MATCH RESULT</p><h2><span class="bn">যাচাইয়ের অপেক্ষায়</span><span class="en">Waiting to verify</span></h2><p>ট্যাগ স্ক্যান করে বুননের ছবি তুলুন।<br>Scan the tag and take a weave photo.</p><div class="result-divider"></div><small>প্রতিটি উত্তর নিবন্ধিত কাপড়ের ফিঙ্গারপ্রিন্টের সঙ্গে তুলনা করা হয়।<br>Every result is checked against the registered fabric fingerprint.</small>';
    }

    function showVerifyResult(result) {
        const card = $("#verify-result");
        const display = {
            genuine: { cls: "result-genuine", icon: "✓", bn: "আসল তাঁতের শাড়ি", en: "GENUINE", copy: "এই বুননটি নিবন্ধিত শাড়ির সঙ্গে মিলেছে। · This weave matches the registered saree." },
            no_match: { cls: "result-no-match", icon: "×", bn: "মিল পাওয়া যায়নি", en: "NO MATCH", copy: "এই বুননটি নিবন্ধিত শাড়ির সঙ্গে মেলেনি। · This weave does not match the registered saree." },
            not_calibrated: { cls: "result-pending", icon: "…", bn: "যাচাই এখনো প্রস্তুত নয়", en: "NOT CALIBRATED", copy: "আসল কাপড়ের উপর যাচাইয়ের মাপকাঠি এখনো ক্যালিব্রেট করা হয়নি। · Matching is waiting for real-fabric calibration." },
            retake: { cls: "result-pending", icon: "↻", bn: "আবার ছবি তুলুন", en: "RETAKE PHOTO", copy: "ছবির গুণমান যাচাই করা যায়নি। আলো ও ফোকাস ঠিক করে আবার তুলুন। · The photo needs better focus or lighting." },
        }[result.result] || { cls: "result-pending", icon: "…", bn: "যাচাই সম্পূর্ণ নয়", en: "UNAVAILABLE", copy: "এই মুহূর্তে ফল পাওয়া যায়নি। · A result is not available right now." };
        card.className = `verify-result-card ${display.cls}`;
        const serverMessage = result.message_bn && result.message_en ? `${result.message_bn} · ${result.message_en}` : result.message_en || result.reason || "";
        card.innerHTML = `<span class="result-seal">${display.icon}</span><p class="eyebrow">MATCH RESULT</p><h2><span class="bn">${display.bn}</span><span class="en">${display.en}</span></h2><p>${display.copy}</p>${result.score != null ? `<div class="result-divider"></div><small>Match score · মিলের স্কোর: ${Number(result.score).toFixed(3)}</small>` : `<div class="result-divider"></div><small>${escapeHtml(serverMessage || "ফলটি সার্ভার থেকে এসেছে · Result returned by the server")}</small>`}`;
    }

    async function submitVerification(photo) {
        if (!currentVerifyQr) return showToast("আগে QR ট্যাগ স্ক্যান করুন · Scan the QR tag first", true);
        if (!navigator.onLine) return showToast("যাচাই করতে ইন্টারনেট দরকার · Verification needs an internet connection", true);
        const button = $("#verify-capture");
        button.disabled = true;
        const card = $("#verify-result");
        card.className = "verify-result-card result-pending";
        card.innerHTML = '<span class="result-seal">⟳</span><p class="eyebrow">MATCH RESULT</p><h2><span class="bn">মিলিয়ে দেখা হচ্ছে</span><span class="en">Checking the weave</span></h2><p>একটু অপেক্ষা করুন · Please wait a moment.</p>';
        const data = new FormData();
        data.append("upload_id", createId());
        if (photo.size > 25 * 1024 * 1024) {
            button.disabled = false;
            card.className = "verify-result-card result-pending";
            card.innerHTML = '<span class="result-seal">!</span><p class="eyebrow">MATCH RESULT</p><h2><span class="bn">ছবিটি খুব বড়</span><span class="en">Photo is too large</span></h2><p>২৫ MB-এর কম ছবি বেছে নিন · Choose a photo under 25 MB.</p>';
            return;
        }
        data.append("photos", photo, photoFilename(photo, `${currentVerifyQr}-check`));
        try {
            const result = await api(`/verify/${encodeURIComponent(currentVerifyQr)}`, { method: "POST", body: data });
            showVerifyResult(result);
            beepAndBuzz();
        } catch (error) {
            card.className = "verify-result-card result-pending";
            card.innerHTML = `<span class="result-seal">!</span><p class="eyebrow">MATCH RESULT</p><h2><span class="bn">যাচাই করা যায়নি</span><span class="en">Could not verify</span></h2><p>${escapeHtml(error.message)}</p><div class="result-divider"></div><small>আবার চেষ্টা করুন · Please try again.</small>`;
        } finally {
            button.disabled = !currentVerifyQr;
        }
    }

    async function captureVerificationPhoto(file = null) {
        let photo = file;
        if (!photo) {
            const track = mediaStream?.getVideoTracks()[0];
            if (track && "ImageCapture" in window) {
                try { photo = await new window.ImageCapture(track).takePhoto(); } catch { /* use native camera picker */ }
            }
        }
        if (!photo) return $("#verify-file").click();
        await submitVerification(photo);
    }

    function applyManualQr(inputSelector, action) {
        const id = parseQrId($(inputSelector).value);
        if (!id) return showToast("ট্যাগ নম্বর লিখুন · Enter a tag ID", true);
        action(id);
    }

    function bindEvents() {
        $("#login-form").addEventListener("submit", async (event) => {
            event.preventDefault();
            const errorBox = $("#login-error");
            setError(errorBox, "");
            const button = $("#login-form button[type='submit']");
            button.disabled = true;
            try {
                const result = await api("/login", { json: { phone: $("#phone").value.trim(), pin: $("#pin").value.trim() } });
                await enterApp(result);
            } catch (error) {
                setError(errorBox, error.message || "লগ ইন হয়নি · Sign in failed");
            } finally {
                button.disabled = false;
            }
        });
        $("#show-pin").addEventListener("click", showPin);
        $("#user-chip").addEventListener("click", clearSession);
        $("#language-toggle").addEventListener("click", () => {
            const next = document.body.dataset.langFirst === "bn" ? "en" : "bn";
            setLanguageMode(next);
        });
        $("#batch-form").addEventListener("submit", submitBatch);
        $("#resume-batch-button").addEventListener("click", resumeBatch);
        $$("[data-action='new-batch']").forEach((button) => button.addEventListener("click", startNewBatch));
        $$("[data-action='home']").forEach((button) => button.addEventListener("click", () => setScreen("home")));
        $$("[data-action='verify'], [data-nav='verify']").forEach((button) => button.addEventListener("click", () => setScreen("verify")));
        $$("[data-action='uploads'], [data-nav='uploads']").forEach((button) => button.addEventListener("click", () => setScreen("uploads")));
        $("[data-nav='home']").addEventListener("click", () => setScreen("home"));
        $("[data-nav='batch']").addEventListener("click", startNewBatch);
        $$(".variety-chip").forEach((button) => button.addEventListener("click", () => {
            $("#saree-type").value = button.dataset.variety;
            $$(".variety-chip").forEach((chip) => chip.classList.toggle("is-selected", chip === button));
        }));
        $("#start-capture-camera").addEventListener("click", () => startCamera("capture"));
        $("#start-verify-camera").addEventListener("click", () => startCamera("verify"));
        $("#capture-now").addEventListener("click", () => captureCurrentPhoto());
        $("#torch-button").addEventListener("click", toggleTorch);
        $("#camera-note").querySelector("button").addEventListener("click", () => $("#capture-file").click());
        $("#choose-photo").addEventListener("click", () => $("#capture-file").click());
        $("#capture-file").addEventListener("change", (event) => {
            const file = event.target.files?.[0];
            if (file) captureCurrentPhoto(true, file);
            event.target.value = "";
        });
        $("#manual-toggle").addEventListener("click", () => { $("#manual-entry").hidden = !$("#manual-entry").hidden; $("#manual-qr-id").focus(); });
        $("#manual-qr-apply").addEventListener("click", () => applyManualQr("#manual-qr-id", onCaptureQr));
        $("#manual-qr-id").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); applyManualQr("#manual-qr-id", onCaptureQr); } });
        $("#capture-help").addEventListener("click", () => showToast("QR ট্যাগ ও মার্কার কার্ড একসঙ্গে দেখান। ছবি ঝাপসা হলে ফোন স্থির রাখুন। · Keep the QR tag and marker card in frame. Hold still if the photo is soft."));
        $("#finish-batch").addEventListener("click", finishBatch);
        $("#next-saree").addEventListener("click", () => { window.clearTimeout(captureSuccessTimer); $("#capture-success").hidden = true; $("#manual-qr-id").value = ""; });
        $("#verify-capture").addEventListener("click", () => captureVerificationPhoto());
        $("#verify-choose-photo").addEventListener("click", () => $("#verify-file").click());
        $("#verify-file").addEventListener("change", (event) => { const file = event.target.files?.[0]; if (file) submitVerification(file); event.target.value = ""; });
        $("#verify-manual-toggle").addEventListener("click", () => { $("#verify-manual-entry").hidden = !$("#verify-manual-entry").hidden; $("#verify-manual-qr").focus(); });
        $("#verify-manual-apply").addEventListener("click", () => applyManualQr("#verify-manual-qr", onVerifyQr));
        $("#verify-manual-qr").addEventListener("keydown", (event) => { if (event.key === "Enter") { event.preventDefault(); applyManualQr("#verify-manual-qr", onVerifyQr); } });
        $("#retry-all").addEventListener("click", () => syncQueue(true));
        $("#upload-list").addEventListener("click", async (event) => {
            const retakeButton = event.target.closest("[data-retake]");
            if (retakeButton) {
                await retakeCapture(retakeButton.dataset.retake);
                return;
            }
            const button = event.target.closest("[data-retry]");
            if (!button) return;
            await updateCapture(button.dataset.retry, { state: "waiting", note: "" });
            renderQueue();
            syncQueue();
        });
        window.addEventListener("online", updateNetworkState);
        window.addEventListener("offline", updateNetworkState);
        if ("serviceWorker" in navigator) navigator.serviceWorker.addEventListener("message", (event) => { if (event.data?.type === "QUEUE_UPDATED") renderQueue(); });
    }

    async function initialize() {
        const savedLanguage = localStorage.getItem("tantsaakshi-language-order") || "bn";
        setLanguageMode(savedLanguage);
        watchBilingualText();
        window.setInterval(refreshServerStatuses, 9000);
        updateNetworkState();
        bindEvents();
        try { await openDb(); } catch (error) { console.warn("Offline storage unavailable", error); }
        const savedSession = getStoredSession();
        if (savedSession?.token) {
            session = savedSession;
            const savedBatch = localStorage.getItem("tantsaakshi-active-batch");
            try {
                const candidate = savedBatch ? JSON.parse(savedBatch) : null;
                activeBatch = candidate && candidate.startedBy === savedSession.name && candidate.coopId === (savedSession.coop_id || null) && savedSession.role !== "seller" ? candidate : null;
                if (candidate && !activeBatch) localStorage.removeItem("tantsaakshi-active-batch");
            } catch { activeBatch = null; }
            if (activeBatch) {
                try {
                    const captures = await getCaptures();
                    latestPerQr(captures.filter((item) => item.batchId === activeBatch.id))
                        .filter((item) => !needsRetake(item))
                        .forEach((item) => batchQrIds.add(item.qrId));
                } catch { /* summary and queue can still be opened */ }
            }
            updateUserChip();
            setScreen("home");
            loadWeavers();
            setupServiceWorker();
            syncQueue();
        } else {
            setScreen("login");
        }
    }

    initialize();
})();

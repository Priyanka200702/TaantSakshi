/* TantSaakshi in-app camera.
   "Camera" buttons ask for camera permission and open a live viewfinder with a
   shutter, instead of a file picker. Uses the back camera, full-resolution
   stills where the browser allows (ImageCapture), and the torch if the phone
   has one. Falls back to the phone's own camera app when the page isn't on
   HTTPS/localhost (browsers block live camera access there).

   window.TSCamera.open({ max, onCapture(files) })
*/
(() => {
  "use strict";
  const live = !!(window.isSecureContext && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  let ui = null, stream = null, track = null, shots = [], opts = null, facing = "environment", torchOn = false;

  function el(html) { const d = document.createElement("div"); d.innerHTML = html.trim(); return d.firstChild; }

  function build() {
    ui = el(`
      <div class="tscam" role="dialog" aria-modal="true" aria-label="Camera">
        <div class="tscam-view">
          <video playsinline muted autoplay></video>
          <div class="tscam-guide" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
          <p class="tscam-hint">Fit the marker card inside the frame · all 4 corners visible<br><span>কার্ডটি ফ্রেমের ভেতরে রাখুন</span></p>
          <div class="tscam-flash"></div>
          <p class="tscam-msg" hidden></p>
        </div>
        <div class="tscam-top">
          <button type="button" class="tscam-icon" data-act="close" aria-label="Close camera">✕</button>
          <span class="tscam-count">0 / 5</span>
          <button type="button" class="tscam-icon" data-act="torch" aria-label="Torch" hidden>⚡</button>
        </div>
        <div class="tscam-bar">
          <div class="tscam-thumbs"></div>
          <button type="button" class="tscam-shutter" data-act="shoot" aria-label="Take photo"><span></span></button>
          <div class="tscam-side">
            <button type="button" class="tscam-icon" data-act="flip" aria-label="Switch camera" hidden>⟲</button>
            <button type="button" class="tscam-done" data-act="done" disabled>Use <b>0</b></button>
          </div>
        </div>
      </div>`);
    ui.addEventListener("click", (e) => {
      const act = e.target.closest("[data-act]")?.dataset.act;
      if (act === "close") close(false);
      if (act === "shoot") shoot();
      if (act === "done") close(true);
      if (act === "flip") { facing = facing === "environment" ? "user" : "environment"; start(); }
      if (act === "torch") toggleTorch();
    });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(ui);
    document.body.classList.add("tscam-open");
  }

  function onKey(e) {
    if (!ui) return;
    if (e.key === "Escape") close(false);
    if (e.key === " " || e.key === "Enter") { e.preventDefault(); shoot(); }
  }

  function msg(text) {
    const m = ui.querySelector(".tscam-msg");
    m.textContent = text || ""; m.hidden = !text;
  }

  async function start() {
    stopStream();
    msg("");
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: facing }, width: { ideal: 4096 }, height: { ideal: 3072 } },
      });
    } catch (err) {
      const why = err && err.name === "NotAllowedError"
        ? "Camera permission was refused. Allow the camera in the browser's site settings, then try again. · ক্যামেরার অনুমতি দিন।"
        : err && (err.name === "NotFoundError" || err.name === "OverconstrainedError")
          ? "No camera found on this device. Use Gallery instead. · ক্যামেরা পাওয়া যায়নি।"
          : "Couldn't start the camera. Close other apps using it and try again.";
      msg(why);
      return;
    }
    track = stream.getVideoTracks()[0];
    const v = ui.querySelector("video");
    v.srcObject = stream;
    try { await v.play(); } catch { /* autoplay will start it */ }
    // torch + camera switch only when the device supports them
    const caps = track.getCapabilities ? track.getCapabilities() : {};
    ui.querySelector('[data-act="torch"]').hidden = !caps.torch;
    torchOn = false;
    try {
      const cams = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
      ui.querySelector('[data-act="flip"]').hidden = cams.length < 2;
    } catch { /* ignore */ }
  }

  async function toggleTorch() {
    if (!track) return;
    torchOn = !torchOn;
    try { await track.applyConstraints({ advanced: [{ torch: torchOn }] }); }
    catch { torchOn = false; }
    ui.querySelector('[data-act="torch"]').classList.toggle("on", torchOn);
  }

  async function grab() {
    // Full sensor resolution where supported (Chrome on Android), else the video frame.
    if (window.ImageCapture && track) {
      try {
        const blob = await new ImageCapture(track).takePhoto();
        if (blob && blob.size) return blob.type === "image/jpeg" ? blob : await reencode(blob);
      } catch { /* fall back to the frame */ }
    }
    const v = ui.querySelector("video");
    const c = document.createElement("canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d").drawImage(v, 0, 0);
    return new Promise((res) => c.toBlob(res, "image/jpeg", 0.95));
  }

  async function reencode(blob) {
    const bmp = await createImageBitmap(blob);
    const c = document.createElement("canvas");
    c.width = bmp.width; c.height = bmp.height;
    c.getContext("2d").drawImage(bmp, 0, 0);
    return new Promise((res) => c.toBlob(res, "image/jpeg", 0.95));
  }

  let busy = false;
  async function shoot() {
    if (!track || busy || shots.length >= opts.max) return;
    busy = true;
    const f = ui.querySelector(".tscam-flash");
    f.classList.remove("go"); void f.offsetWidth; f.classList.add("go");
    if (navigator.vibrate) navigator.vibrate(15);
    try {
      const blob = await grab();
      if (blob) {
        const file = new File([blob], `photo_${Date.now()}_${shots.length + 1}.jpg`, { type: "image/jpeg", lastModified: Date.now() });
        shots.push(file);
        const t = document.createElement("img");
        t.src = URL.createObjectURL(file); t.alt = `Photo ${shots.length}`;
        ui.querySelector(".tscam-thumbs").appendChild(t);
      }
    } finally { busy = false; update(); }
  }

  function update() {
    ui.querySelector(".tscam-count").textContent = `${shots.length} / ${opts.max}`;
    const done = ui.querySelector(".tscam-done");
    done.disabled = !shots.length;
    done.querySelector("b").textContent = shots.length;
    ui.querySelector(".tscam-shutter").disabled = shots.length >= opts.max;
  }

  function stopStream() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null; track = null;
  }

  function close(use) {
    stopStream();
    document.removeEventListener("keydown", onKey);
    document.body.classList.remove("tscam-open");
    if (ui) { ui.querySelectorAll(".tscam-thumbs img").forEach((i) => URL.revokeObjectURL(i.src)); ui.remove(); ui = null; }
    const files = shots; shots = [];
    if (use && files.length && opts && opts.onCapture) opts.onCapture(files);
  }

  window.TSCamera = {
    live,
    open(o) {
      opts = { max: 5, ...o };
      if (opts.max <= 0) return;
      shots = []; facing = "environment";
      build(); update(); start();
    },
  };

  // ---- wire the app's "Camera" buttons ----
  // Each camera <input> keeps working as the fallback (phone camera app) when live camera is blocked.
  const WIRES = [
    { input: "captureInput", handler: "onPhotosSelected" },
    { input: "regCapture", handler: "onRegPhotos" },
  ];
  WIRES.forEach(({ input, handler }) => {
    const inp = document.getElementById(input);
    const label = document.querySelector(`label[for="${input}"]`);
    if (!inp || !label) return;
    label.addEventListener("click", (e) => {
      if (!live) return; // let the browser open the phone's camera app instead
      e.preventDefault();
      const already = document.querySelectorAll(input === "captureInput" ? "#previewStrip img" : "#regPhotoPreview img").length;
      window.TSCamera.open({
        max: Math.max(1, 5 - already),
        onCapture: (files) => { if (typeof window[handler] === "function") window[handler]({ files }); },
      });
    });
  });
})();

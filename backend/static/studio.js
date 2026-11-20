/* TantSaakshi voice studio upgrades (loaded after the main script).
   - Real speech-to-text while recording (browser speech recognition, Bengali),
     shown live; "Fill listing from my voice" builds the listing from the words.
     Falls back to the clearly marked sample only when the browser can't transcribe.
   - Saree picker keeps listed sarees (marked), so a listing can be edited/re-shared.
   - ONDC: readable preview + readiness checklist + download, instead of raw JSON. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ---------------- 1. picker: show every certified saree ---------------- */
  window.renderStudioSareePicker = function () {
    const box = $("studioUnlistedList"), none = $("studioNoneUnlisted");
    box.innerHTML = "";
    const all = (studioSarees || []).slice().sort((a, b) => (!!a.listing - !!b.listing));
    if (!all.length) { none.style.display = "block"; return; }
    none.style.display = "none";
    all.forEach((s) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "studio-saree-btn" + (studioQrId === s.qr_id ? " selected" : "");
      b.onclick = () => selectStudioSaree(s.qr_id);
      const price = s.listing && s.listing.price_inr ? ` · ₹${Number(s.listing.price_inr).toLocaleString("en-IN")}` : "";
      b.innerHTML = `
        <img src="${esc(s.photo_url || "/c/" + s.qr_id + "/photo")}" alt="" class="studio-saree-thumb" onerror="this.onerror=null;this.src='/static/saree-corners.svg'"/>
        <div style="flex:1;overflow:hidden;text-align:left">
          <div style="font-weight:700;font-size:.85rem;color:var(--maroon);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(s.saree_type || "Saree")} · ${esc(s.district || "")}</div>
          <div style="font-family:monospace;font-size:.7rem;letter-spacing:.1em;color:var(--text-muted2);margin-top:.15rem">${esc(s.qr_id)} · EPI ${s.ends_per_inch ? s.ends_per_inch.toFixed(1) : "—"}</div>
        </div>
        ${s.listing ? `<span class="studio-listed">Listed${esc(price)}</span>` : `<span class="studio-new">New</span>`}`;
      box.appendChild(b);
    });
  };

  /* ---------------- 2. selecting a listed saree loads its listing ---------------- */
  const FIELDS = ["title_en", "title_bn", "colour", "motif", "occasion", "price_inr", "story_bn", "story_en"];
  const origSelect = window.selectStudioSaree;
  window.selectStudioSaree = function (qrId) {
    origSelect(qrId);
    const s = (studioSarees || []).find((x) => x.qr_id === qrId);
    const L = s && s.listing;
    FIELDS.forEach((k) => {
      const el = $("field_" + k);
      if (!el) return;
      if (!L) { el.value = ""; return; }
      el.value = k === "title_en" ? (L.title || "") : k === "title_bn" ? "" : (L[k] == null ? "" : L[k]);
    });
    $("studioPublishLabel").textContent = L ? "Update listing" : "Publish listing";
    $("studioFieldsCard").style.display = L ? "block" : "none";
    $("studioShareCard").style.display = L ? "block" : "none";
    if (L) $("studioCertLink").href = `/c/${qrId}`;
    $("studioError").style.display = "none";
  };

  // after publishing, refresh the list so the saree shows as "Listed" (it no longer disappears)
  const origPublish = window.publishStudioListing;
  window.publishStudioListing = async function () {
    await origPublish();
    try {
      const r = await apiFetch("GET", "/listings");
      studioSarees = r.listings || [];
      renderStudioSareePicker();
      $("studioPublishLabel").textContent = "Update listing";
    } catch { /* keep the old list */ }
  };

  /* ---------------- 3. real speech-to-text while recording ---------------- */
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, finalText = "", liveText = "", srProblem = "";
  window.studioSpeech = "";

  function showTranscript(text, live) {
    const box = $("studioTranscriptBox");
    if (!text && !live) { box.style.display = "none"; return; }
    box.style.display = "block";
    $("studioTranscriptText").innerHTML = `${esc(text)}${live ? ` <span class="studio-live">${esc(live)}</span>` : ""}`;
  }

  function startRecognition() {
    finalText = ""; liveText = ""; srProblem = ""; window.__tsTextOnly = false;
    if (!SR) { srProblem = "This browser can't turn speech into text. Use Chrome, or type the story."; return; }
    try {
      rec = new SR();
      rec.lang = "bn-IN";
      rec.continuous = true;
      rec.interimResults = true;
      rec.onresult = (e) => {
        liveText = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const t = e.results[i][0].transcript;
          if (e.results[i].isFinal) finalText += (finalText ? " " : "") + t.trim();
          else liveText += t;
        }
        showTranscript(finalText, liveText);
      };
      rec.onerror = (e) => {
        // Some phones can't record audio and transcribe at once: keep the words, drop the audio copy.
        if (e.error === "audio-capture" && studioRecording && !window.__tsTextOnly &&
            typeof studioMediaRecorder !== "undefined" && studioMediaRecorder && studioMediaRecorder.state === "recording") {
          window.__tsTextOnly = true;
          try { studioMediaRecorder.stop(); } catch { /* already stopped */ }
          note("Listening for words only on this phone (audio copy paused). Keep speaking. · কথা শোনা চলছে।", "warn");
          return;   // onend restarts recognition while recording is on
        }
        srProblem = e.error === "not-allowed" ? "Speech-to-text was blocked. Allow the microphone for this site."
          : e.error === "network" ? "Speech-to-text needs an internet connection."
          : e.error === "audio-capture" ? "Speech-to-text couldn't use the microphone here. Type the story instead."
          : e.error === "no-speech" ? "" : "Speech-to-text stopped (" + e.error + ").";
      };
      rec.onend = () => { if (studioRecording && rec) { try { rec.start(); } catch { /* already running */ } } };
      rec.start();
    } catch { srProblem = "Speech-to-text couldn't start."; rec = null; }
  }

  function stopRecognition() {
    const r = rec; rec = null;
    if (r) { try { r.stop(); } catch { /* ignore */ } }
    setTimeout(() => {
      window.studioSpeech = (finalText + " " + liveText).trim();
      showTranscript(window.studioSpeech, "");
      const label = $("studioTranscribeLabel");
      if (label) label.textContent = window.studioSpeech ? "Fill listing from my voice" : "Fill a sample listing";
      if (srProblem) note(srProblem, "warn");
    }, 600);
  }

  const origStart = window.startStudioRecording;
  window.startStudioRecording = async function () {
    await origStart();
    if (studioRecording) startRecognition();
  };
  const origStop = window.stopStudioRecording;
  window.stopStudioRecording = function () {
    origStop();
    stopRecognition();
  };

  function note(text, kind) {
    const box = $("studioError");
    box.textContent = text;
    box.style.display = text ? "block" : "none";
    box.style.background = kind === "ok" ? "#f0fdf4" : "#fff8e6";
    box.style.borderColor = kind === "ok" ? "#86efac" : "#e0bf62";
    box.style.color = kind === "ok" ? "#14532d" : "#5a3a00";
  }

  /* --- turn the words into listing fields (simple, transparent rules; staff check them) --- */
  const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
  const toLatin = (s) => s.replace(/[০-৯]/g, (d) => BN_DIGITS.indexOf(d));
  const NUM_WORDS = { "এক": 1, "দুই": 2, "দু": 2, "তিন": 3, "চার": 4, "পাঁচ": 5, "ছয়": 6, "ছয়": 6, "সাত": 7, "আট": 8, "নয়": 9, "নয়": 9, "দশ": 10 };
  const TYPES = [["জামদানি", "Jamdani"], ["বালুচরী", "Baluchari"], ["বালুচরি", "Baluchari"], ["টাঙ্গাইল", "Tangail"], ["ধনেখালি", "Dhaniakhali tant"], ["ধনিয়াখালি", "Dhaniakhali tant"], ["শান্তিপুর", "Shantipur tant"], ["খাদি", "Khadi"], ["কাঁথা", "Kantha"], ["তাঁত", "Tant"]];
  const COLOURS = [["লাল", "Red"], ["সাদা", "White"], ["কালো", "Black"], ["নীল", "Blue"], ["সবুজ", "Green"], ["হলুদ", "Yellow"], ["কমলা", "Orange"], ["গোলাপি", "Pink"], ["বেগুনি", "Purple"], ["সোনালি", "Gold"], ["সোনালী", "Gold"], ["ক্রিম", "Cream"], ["মেরুন", "Maroon"], ["খয়েরি", "Brown"], ["আকাশি", "Sky blue"]];
  const OCCASIONS = [["দুর্গাপুজো", "Durga Puja"], ["পুজো", "Puja"], ["পূজা", "Puja"], ["বিয়ে", "Wedding"], ["বিয়ে", "Wedding"], ["উৎসব", "Festive"], ["ঈদ", "Eid"], ["অফিস", "Office wear"], ["প্রতিদিন", "Daily wear"], ["রোজ", "Daily wear"]];
  const MOTIFS = [["কলকা", "Paisley"], ["বুটি", "Butis"], ["ফুল", "Floral"], ["চেক", "Checks"], ["ডোরা", "Stripes"], ["পাড়", "Border work"], ["আঁচল", "Decorated aanchal"]];

  const found = (text, list) => {
    const out = [];
    list.forEach(([bn, en]) => { if (text.includes(bn) && !out.some((o) => o.en === en)) out.push({ bn, en }); });
    return out;
  };

  function parsePrice(raw) {
    const t = toLatin(raw).replace(/,/g, "");
    let m = t.match(/(?:₹|rs\.?|rupees?)\s*(\d{2,7})/i) || t.match(/(\d{2,7})\s*(?:টাকা|টাকায়|rupees?|rs)/i);
    if (m) return Number(m[1]);
    m = t.match(/(সাড়ে\s*)?(\d{1,2}|এক|দুই|দু|তিন|চার|পাঁচ|ছয়|ছয়|সাত|আট|নয়|নয়|দশ)\s*হাজার/);
    if (m) {
      const n = /\d/.test(m[2]) ? Number(m[2]) : NUM_WORDS[m[2]];
      if (n) return (n + (m[1] ? 0.5 : 0)) * 1000;
    }
    return null;
  }

  function fieldsFromSpeech(text) {
    const types = found(text, TYPES), cols = found(text, COLOURS), occ = found(text, OCCASIONS), mot = found(text, MOTIFS);
    const typeEn = types[0] ? types[0].en : "Handloom";
    const typeBn = types[0] ? types[0].bn : "তাঁতের";
    const colEn = cols.slice(0, 2).map((c) => c.en).join(" & ");
    const colBn = cols.slice(0, 2).map((c) => c.bn).join(" ও ");
    return {
      title_en: `${colEn ? colEn + " " : ""}${typeEn} saree`,
      title_bn: `${colBn ? colBn + " " : ""}${typeBn} শাড়ি`,
      colour: cols.map((c) => `${c.en} (${c.bn})`).join(", "),
      motif: mot.map((c) => `${c.en} (${c.bn})`).join(", "),
      occasion: occ.map((c) => `${c.en} (${c.bn})`).join(", "),
      price_inr: parsePrice(text),
      story_bn: text,
      story_en: "",
    };
  }

  const origTranscribe = window.transcribeStudioVoice;
  window.transcribeStudioVoice = async function () {
    const text = (window.studioSpeech || "").trim();
    if (!text) { await origTranscribe(); return; }   // nothing heard: clearly marked sample
    const f = fieldsFromSpeech(text);
    studioTranscript = text; studioFields = f;
    showTranscript(text, "");
    FIELDS.forEach((k) => { const el = $("field_" + k); if (el) el.value = f[k] == null ? "" : f[k]; });
    $("studioFieldsCard").style.display = "block";
    note("Filled from your own words. Check every field, add the English story if you like, then publish. · আপনার কথা থেকে পূরণ করা হয়েছে — দেখে নিন।", "ok");
    toast("Listing filled from your voice", "🎙");
    $("studioFieldsCard").scrollIntoView({ behavior: "smooth", block: "start" });
  };

  /* ---------------- 4. ONDC: readable preview + checklist ---------------- */
  window.loadStudioOndc = async function () {
    if (!studioQrId) { toast("Choose a saree first", "⚠"); return; }
    let d;
    try { d = await apiFetch("GET", `/ondc/${studioQrId}`); }
    catch (e) { toast(e.message || "ONDC preview not available for this saree yet", "⚠"); return; }
    studioOndcJson = JSON.stringify(d, null, 2);
    const prov = (((d.message || {}).catalog || {})["bpp/providers"] || [])[0] || {};
    const item = (prov.items || [])[0] || {};
    const desc = item.descriptor || {}, tags = item.tags || {};
    const checks = [
      ["Product name", !!desc.name],
      ["Photo of the cloth", !!(desc.images && desc.images.length)],
      ["Price", !!item.price],
      ["Seller (cooperative)", !!(prov.descriptor && prov.descriptor.name)],
      ["Thread count", !!(tags.epi && tags.ppi)],
      ["Birth certificate link", !!tags.certificate_url],
    ];
    const ready = checks.every((c) => c[1]);
    let view = $("studioOndcView");
    if (!view) {
      view = document.createElement("div");
      view.id = "studioOndcView";
      const pre = $("studioOndcCode");
      pre.parentNode.insertBefore(view, pre);
      const det = document.createElement("details");
      det.className = "ondc-tech";
      det.innerHTML = "<summary>Technical data (ONDC / Beckn JSON)</summary>";
      pre.parentNode.insertBefore(det, pre);
      det.appendChild(pre);
    }
    view.innerHTML = `
      <p class="ondc-note">${ready ? "✓ Ready to hand to an ONDC seller app" : "Almost ready — fill the missing items"} · <span>Draft only: TantSaakshi prepares the item; listing on the ONDC network needs the cooperative registered through an ONDC seller app.</span></p>
      <div class="ondc-card">
        ${desc.images && desc.images[0] ? `<img src="${esc(new URL(desc.images[0], location.origin).pathname)}" alt="">` : ""}
        <div>
          <p class="ondc-name">${esc(desc.name || "—")}</p>
          <p class="ondc-price">${item.price ? "₹" + Number(item.price.value).toLocaleString("en-IN") : "No price yet"}</p>
          <p class="ondc-seller">${esc(prov.descriptor && prov.descriptor.name || "")}</p>
          <p class="ondc-meta">${tags.craft ? esc(tags.craft) + " · " : ""}${tags.epi ? "EPI " + esc(tags.epi) + " × PPI " + esc(tags.ppi) : ""} · Grade ${esc(tags.grade || "provisional")}</p>
        </div>
      </div>
      <ul class="ondc-checks">${checks.map(([k, ok]) => `<li class="${ok ? "ok" : "miss"}">${ok ? "✓" : "✗"} ${k}${!ok && k === "Price" ? " — add a price and update the listing" : ""}</li>`).join("")}</ul>
      <button type="button" class="btn-gold ondc-dl">Download JSON</button>`;
    view.querySelector(".ondc-dl").onclick = () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([studioOndcJson], { type: "application/json" }));
      a.download = `ondc_${studioQrId}.json`;
      a.click();
    };
    $("studioOndcCode").textContent = studioOndcJson;
    $("studioOndcModal").classList.remove("hidden");
  };
})();

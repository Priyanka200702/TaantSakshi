/* TantSaakshi theme behaviour: animations, phone tab bar, live hero numbers,
   and a Register link for staff. Loaded after the main script in app.html. */
(() => {
  "use strict";
  const root = document.documentElement;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  // ---------- hero entrance ----------
  requestAnimationFrame(() => root.classList.add("ts-ready"));

  // ---------- header shadow on scroll ----------
  const nav = $("#navbar");
  const onScroll = () => nav && nav.classList.toggle("scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // ---------- reveal on scroll ----------
  const io = "IntersectionObserver" in window && !reduce
    ? new IntersectionObserver((entries) => {
        entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
      }, { rootMargin: "0px 0px -8% 0px" })
    : null;
  function reveal(scope) {
    const items = $$(
      ".section-eyebrow, .section-title, .section-bn, .step-card, .craft-card, .page-header, .paper-grain, .cat-card, .login-card, .camera-section, .recheck-panel",
      scope || document
    ).filter((el) => !el.classList.contains("ts-reveal") && !el.closest(".hero"));
    items.forEach((el, i) => {
      if (!io) return;
      el.classList.add("ts-reveal");
      el.style.transitionDelay = `${Math.min(i % 4, 3) * 80}ms`;
      io.observe(el);
    });
  }
  reveal();

  // ---------- live hero numbers (only real, processed sarees) ----------
  const bnDigits = (n) => String(n).replace(/\d/g, (d) => "০১২৩৪৫৬৭৮৯"[d]);
  function countUp(el, to, fmt) {
    if (!el) return;
    if (reduce || to <= 0) { el.textContent = fmt(to); return; }
    const t0 = performance.now(), dur = 900;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      el.textContent = fmt(Math.round(to * (1 - Math.pow(1 - k, 3))));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }
  fetch("/listings", { headers: { Accept: "application/json" } })
    .then((r) => (r.ok ? r.json() : Promise.reject()))
    .then((d) => {
      const items = d.listings || [];
      const coops = new Set(items.map((i) => i.cooperative).filter(Boolean));
      countUp($("#statSarees"), items.length, String);
      countUp($("#statCoops"), coops.size, bnDigits);
    })
    .catch(() => {});

  // ---------- phone tab bar + staff Register link ----------
  const tabbar = $("#tabbar");
  const ink = $(".tab-ink");
  const TAB_FOR = { home: "home", verify: "verify", catalogue: "catalogue", studio: "studio", login: "account", register: "account" };

  function syncTabs(name) {
    if (!tabbar) return;
    const key = TAB_FOR[name] || "home";
    $$("button[data-tab]", tabbar).forEach((b, i) => {
      const on = b.dataset.tab === key;
      b.classList.toggle("active", on);
      if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
      if (on && ink) ink.style.left = `${i * 20}%`;
    });
  }

  // desktop: add a Register link that only staff see
  const links = $(".nav-links");
  let regLink = $("#nav-register");
  if (links && !regLink) {
    regLink = document.createElement("button");
    regLink.className = "nav-link";
    regLink.id = "nav-register";
    regLink.type = "button";
    regLink.style.display = "none";
    regLink.innerHTML = 'Register <span class="bn">নিবন্ধন</span>';
    regLink.addEventListener("click", () => window.showPage("register"));
    links.insertBefore(regLink, $("#nav-login-btn"));
  }

  function signedInUser() {
    try { return JSON.parse(localStorage.getItem("ts_auth") || "null"); } catch { return null; }
  }
  function syncAuth() {
    const u = signedInUser();
    const staff = !!u && u.role !== "seller";
    if (regLink) regLink.style.display = staff ? "" : "none";
    const lbl = $("#tabAccountLabel");
    if (lbl) lbl.textContent = u ? (staff ? "Desk" : "Account") : "Login";
  }

  // wrap the app's functions so tabs and links follow every page change / login
  if (typeof window.showPage === "function") {
    const orig = window.showPage;
    window.showPage = function (name) {
      closeSheet();
      orig.apply(this, arguments);
      syncTabs(name);
      reveal($("#page-" + name));
    };
  }
  if (typeof window.updateNavAuth === "function") {
    const origAuth = window.updateNavAuth;
    window.updateNavAuth = function () { origAuth.apply(this, arguments); syncAuth(); };
  }

  // account tab: login when signed out, small sheet when signed in
  let sheet = null;
  function closeSheet() { if (sheet) { sheet.remove(); sheet = null; } }
  window.tabAccount = function () {
    const u = signedInUser();
    if (!u) { window.showPage("login"); return; }
    if (sheet) { closeSheet(); return; }
    const staff = u.role !== "seller";
    sheet = document.createElement("div");
    sheet.className = "ts-sheet";
    sheet.innerHTML = `
      <div class="ts-sheet-card" role="dialog" aria-label="Account">
        <p class="ts-sheet-who">${(u.name || u.phone || "").replace(/[<>&]/g, "")}</p>
        ${staff ? '<button type="button" data-act="register">Register a saree <span class="bn">শাড়ি নিবন্ধন</span></button>' : ""}
        ${staff ? '<button type="button" data-act="studio">Voice studio <span class="bn">স্টুডিও</span></button>' : '<button type="button" data-act="verify">Re-check a saree <span class="bn">যাচাই</span></button>'}
        <button type="button" data-act="logout" class="danger">Sign out <span class="bn">বের হন</span></button>
      </div>`;
    sheet.addEventListener("click", (e) => {
      const act = e.target.closest("button")?.dataset.act;
      if (!act) { if (e.target === sheet) closeSheet(); return; }
      closeSheet();
      if (act === "logout") { window.logout(); syncAuth(); syncTabs("home"); }
      else window.showPage(act);
    });
    document.body.appendChild(sheet);
  };

  syncAuth();
  const activePage = document.querySelector(".page.active");
  syncTabs(activePage ? activePage.id.replace("page-", "") : "home");
})();

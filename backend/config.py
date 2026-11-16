"""
backend/config.py
Central configuration for TantSaakshi backend.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure TantSaakshi project root is in sys.path so 'engine' can be imported anywhere
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

# Base URL for permanent QR codes
BASE_URL = os.getenv("TANTSAAKSHI_BASE_URL", os.getenv("BASE_URL", "https://tantsaakshi.org")).rstrip("/")

# Storage directories
STORAGE_DIR = Path(os.getenv("TANTSAAKSHI_STORAGE_DIR", str(BACKEND_DIR / "storage")))
IMAGES_DIR = STORAGE_DIR / "images"
FINGERPRINTS_DIR = STORAGE_DIR / "fingerprints"
TAGS_PDF_DIR = STORAGE_DIR / "tags_pdf"
BACKUPS_DIR = STORAGE_DIR / "backups"

for directory in [STORAGE_DIR, IMAGES_DIR, FINGERPRINTS_DIR, TAGS_PDF_DIR, BACKUPS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{STORAGE_DIR / 'tantsaakshi.db'}")

# Security
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required; refuse to start without it.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 days token expiry

# Upload limits
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB per image
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}

# Anti-counterfeit scan warning threshold
SCAN_WARNING_THRESHOLD = int(os.getenv("SCAN_WARNING_THRESHOLD", "10"))
SCAN_WINDOW_HOURS = int(os.getenv("SCAN_WINDOW_HOURS", "24"))

# Bilingual error and rejection messages
BILINGUAL_MESSAGES: dict[str, dict[str, str]] = {
    "NO_CARD": {
        "en": "Could not find the measurement card. Please ensure the full card and all 4 markers are visible.",
        "bn": "পরিমাপ কার্ডটি সনাক্ত করা যায়নি। অনুগ্রহ করে নিশ্চিত করুন যে পুরো কার্ড এবং ৪টি মার্কার পরিষ্কার দেখা যাচ্ছে।",
    },
    "TOO_TILTED": {
        "en": "Camera angle is too tilted. Please hold the phone directly above the card.",
        "bn": "ক্যামেরার কোণটি খুব বেশি বাঁকা। অনুগ্রহ করে ফোনটি কার্ডের ঠিক উপরে সোজা করে ধরুন।",
    },
    "LOW_RES": {
        "en": "Image resolution is too low. Please move the camera closer or ensure good focus.",
        "bn": "ছবির রেজোলিউশন খুব কম। অনুগ্রহ করে ক্যামেরাটি আরও কাছে আনুন বা ভালো ফোকাস করুন।",
    },
    "TOO_DARK": {
        "en": "Lighting is too dark. Please use better lighting or flash.",
        "bn": "আলো খুব কম। অনুগ্রহ করে ভালো আলো বা ফ্ল্যাশ ব্যবহার করুন।",
    },
    "GLARE": {
        "en": "Too much glare or light reflection on the fabric. Please adjust your angle or lighting.",
        "bn": "কাপড়ের উপর অতিরিক্ত আলোর ঝলক রয়েছে। অনুগ্রহ করে আলোর উৎস বা কোণ পরিবর্তন করুন।",
    },
    "BLURRY": {
        "en": "The photograph is blurry. Please hold the phone steady and refocus.",
        "bn": "ছবিটি ঝাপসা। অনুগ্রহ করে ফোনটি স্থির রেখে পুনরায় ফোকাস করুন।",
    },
    "NO_WEAVE": {
        "en": "Fabric weave pattern could not be detected. Please ensure the cut-out shows clear fabric.",
        "bn": "কাপড়ের বুনন প্যাটার্ন সনাক্ত করা যায়নি। অনুগ্রহ করে নিশ্চিত করুন কাট-আউটে কাপড় পরিষ্কার দেখা যাচ্ছে।",
    },
    "ALIASING": {
        "en": "Camera is too far away to resolve individual threads. Please move closer.",
        "bn": "ক্যামেরাটি খুব দূরে থাকায় পৃথক সুতা বোঝা যাচ্ছে না। অনুগ্রহ করে আরও কাছে আনুন।",
    },
    "WEAVE_UNCLEAR": {
        "en": "Weave unclear: move the card to another plain spot",
        "bn": "বুনন অস্পষ্ট: কার্ডটি অন্য একটি সাধারণ জায়গায় সরান",
    },
    "DESIGN_AREA": {
        "en": "Measurement window is placed on an ornamental motif. Please place it on plain woven ground fabric.",
        "bn": "পরিমাপ উইন্ডোটি ডিজাইনের উপর পড়েছে। অনুগ্রহ করে এটি সাধারণ সমতল বুনন কাপড়ের উপর রাখুন।",
    },
    "BAD_IMAGE": {
        "en": "Corrupt or unreadable image file. Please capture again.",
        "bn": "ত্রুটিপূর্ণ বা অপাঠ্য ছবি। অনুগ্রহ করে পুনরায় ছবি তুলুন।",
    },
    "TAG_UNKNOWN": {
        "en": "Not a valid TantSaakshi tag.",
        "bn": "এটি একটি বৈধ তাঁতসাক্ষী ট্যাগ নয়।",
    },
    "TAG_USED": {
        "en": "This tag has already been registered.",
        "bn": "এই ট্যাগটি ইতিমধ্যে নিবন্ধিত হয়েছে।",
    },
    "TAG_OTHER_COOP": {
        "en": "This tag belongs to another cooperative.",
        "bn": "এই ট্যাগটি অন্য একটি সমবায় সমিতির অন্তর্ভুক্ত।",
    },
    "AUTH_FAILED": {
        "en": "Wrong phone or PIN",
        "bn": "ভুল ফোন নম্বর বা পিন",
    },
    "BATCH_UNKNOWN": {
        "en": "Batch not found.",
        "bn": "ব্যাচটি পাওয়া যায়নি।",
    },
    "BATCH_OTHER_COOP": {
        "en": "Batch belongs to another cooperative.",
        "bn": "ব্যাচটি অন্য সমবায় সমিতির অন্তর্ভুক্ত।",
    },
    "WEAVER_UNKNOWN": {
        "en": "Weaver not found.",
        "bn": "তাঁতিকে পাওয়া যায়নি।",
    },
    "WEAVER_OTHER_COOP": {
        "en": "Weaver belongs to another cooperative.",
        "bn": "তাঁতি অন্য সমবায় সমিতির অন্তর্ভুক্ত।",
    },
    "FINGERPRINT_NOT_FOUND": {
        "en": "Original registered fingerprint not found for this saree.",
        "bn": "এই শাড়ির মূল নিবন্ধিত ফিঙ্গারপ্রিন্ট পাওয়া যায়নি।",
    },
    "GENUINE": {
        "en": "Fabric fingerprint matches registered weave.",
        "bn": "কাপড়ের ফিঙ্গারপ্রিন্ট নিবন্ধিত বুননের সাথে মিলে গেছে।",
    },
    "NO_MATCH": {
        "en": "Fabric fingerprint does not match registered weave.",
        "bn": "কাপড়ের ফিঙ্গারপ্রিন্ট নিবন্ধিত বুননের সাথে মেলেনি।",
    },
    "NOT_CALIBRATED": {
        "en": "Matching threshold is not yet calibrated on real fabric photos. Verification is pending calibration.",
        "bn": "আসল কাপড়ের ছবির উপর ম্যাচিং থ্রেশহোল্ড এখনও ক্যালিব্রেট করা হয়নি। যাচাইকরণ ক্যালিব্রেশনের অপেক্ষায় রয়েছে।",
    },
    "RETAKE": {
        "en": "Photograph quality unsuitable. Please retake photo.",
        "bn": "ছবির গুণমান উপযুক্ত নয়। অনুগ্রহ করে আবার ছবি তুলুন।",
    },
    "REGISTRATION_PENDING": {
        "en": "Saree registration image processing is still underway. Please wait for completion.",
        "bn": "শাড়ির নিবন্ধন প্রক্রিয়া এখনও চলছে। অনুগ্রহ করে অপেক্ষা করুন।",
    },
    "REGISTRATION_FAILED": {
        "en": "Original saree registration failed quality analysis. Verification cannot be performed.",
        "bn": "মূল শাড়ির নিবন্ধন গুণমান পরীক্ষায় ব্যর্থ হয়েছে। যাচাইকরণ সম্ভব নয়।",
    },
    "MATCH_FAILED": {
        "en": "Matching failed due to processing error.",
        "bn": "ম্যাচিং প্রক্রিয়া ব্যর্থ হয়েছে।",
    },
}

def get_message(code: str, lang: str = "en", default: str = "") -> str:
    """Retrieve bilingual message for an error or rejection code."""
    msgs = BILINGUAL_MESSAGES.get(code)
    if msgs:
        return msgs.get(lang, msgs.get("en", default or code))
    return default or code

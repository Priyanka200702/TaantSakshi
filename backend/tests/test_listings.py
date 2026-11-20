"""Listings, voice studio, share link and ONDC draft: access rules and no made-up values."""
from __future__ import annotations

import json

from backend.config import BASE_URL
from backend.models import Batch, Saree, Tag


def _saree(env, qr="TS-COOPA001", batch="BATCH-A-01", status="done", **kw):
    s = env["session"]
    if not s.query(Tag).filter_by(qr_id=qr).first():
        s.add(Tag(qr_id=qr, coop_id="COOP-A", batch_no="BATCH-A-01", status="blank"))
        s.flush()
    s.add(Saree(qr_id=qr, batch_id=batch, upload_id=f"u-{qr}", image_path="x.jpg",
                epi=kw.get("epi", 54.1), ppi=kw.get("ppi", 92.7), proc_status=status))
    tag = s.query(Tag).filter_by(qr_id=qr).first()
    if tag:
        tag.status = "registered"
    s.commit()


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def test_listings_only_done_no_fake_grade(client, test_env):
    _saree(test_env, "TS-COOPA001", status="done")
    _saree(test_env, "TS-COOPA002", status="queued")
    items = client.get("/listings").json()["listings"]
    assert [i["qr_id"] for i in items] == ["TS-COOPA001"]
    assert items[0]["grade"] is None and items[0]["grade_provisional"] is True
    assert items[0]["photo_url"] == "/c/TS-COOPA001/photo"


def test_weaver_name_only_with_permission(client, test_env):
    s = test_env["session"]
    _saree(test_env, "TS-COOPA001")
    batch = s.query(Batch).filter_by(id="BATCH-A-01").first()
    batch.weaver_id = "WVR-A2"  # Private Weaver: show_name_publicly=False
    s.commit()
    assert client.get("/listings").json()["listings"][0]["weaver"] is None
    batch.weaver_id = "WVR-A1"  # Amiya Basak: agreed
    s.commit()
    assert client.get("/listings").json()["listings"][0]["weaver"] == "Amiya Basak"


def test_publish_needs_login_and_own_coop(client, test_env, token_staff_a, token_staff_b, token_seller):
    _saree(test_env, "TS-COOPA001")
    body = {"title": "Red tant", "price_inr": 2400}
    assert client.post("/listings/TS-COOPA001", json=body).status_code in (401, 403)
    assert client.post("/listings/TS-COOPA001", json=body, headers=_auth(token_seller)).status_code == 403
    assert client.post("/listings/TS-COOPA001", json=body, headers=_auth(token_staff_b)).status_code == 403
    r = client.post("/listings/TS-COOPA001", json=body, headers=_auth(token_staff_a))
    assert r.status_code == 200
    s = test_env["session"]
    s.expire_all()
    assert s.query(Tag).filter_by(qr_id="TS-COOPA001").first().status == "listed"
    saved = json.loads(s.query(Saree).filter_by(qr_id="TS-COOPA001").first().listing_json)
    assert saved["title"] == "Red tant"                      # stored in the database, survives restarts
    assert client.get("/listings").json()["listings"][0]["listing"]["price_inr"] == 2400


def test_cannot_list_blank_or_unprocessed_tag(client, test_env, token_staff_a):
    body = {"title": "x"}
    r = client.post("/listings/TS-COOPA001", json=body, headers=_auth(token_staff_a))   # blank tag
    assert r.status_code == 404
    s = test_env["session"]
    s.expire_all()
    assert s.query(Tag).filter_by(qr_id="TS-COOPA001").first().status == "blank"      # tag still usable
    _saree(test_env, "TS-COOPA002", status="processing")
    assert client.post("/listings/TS-COOPA002", json=body, headers=_auth(token_staff_a)).status_code == 404


def test_transcribe_is_marked_demo_and_needs_login(client, token_staff_a):
    files = {"audio": ("v.webm", b"junk", "audio/webm")}
    assert client.post("/transcribe", files=files).status_code in (401, 403)
    d = client.post("/transcribe", files=files, headers=_auth(token_staff_a)).json()
    assert d["demo"] is True and d["notice_en"] and d["notice_bn"]
    assert d["fields"]["price_inr"] is None
    text = json.dumps(d, ensure_ascii=False)
    for claim in ("lab", "ল্যাব", "three generations", "AI"):
        assert claim not in text


def test_share_link_uses_base_url(client, test_env):
    _saree(test_env, "TS-COOPA001")
    url = client.post("/listings/TS-COOPA001/share", json={"to": "+91 98000 00001"}).json()["share_url"]
    assert url.startswith("https://wa.me/919800000001?text=")
    assert "localhost" not in url or "localhost" in BASE_URL
    assert client.post("/listings/TS-NOPE/share", json={}).status_code == 404


def test_ondc_draft_has_only_real_values(client, test_env):
    assert client.get("/ondc/TS-COOPA001").status_code == 404       # not certified yet
    _saree(test_env, "TS-COOPA001")
    d = client.get("/ondc/TS-COOPA001").json()
    assert d["draft"] is True
    item = d["message"]["catalog"]["bpp/providers"][0]["items"][0]
    assert item["tags"]["epi"] == "54.1" and item["tags"]["ppi"] == "92.7"
    assert item["tags"]["grade"] == "provisional"
    assert "price" not in item                                         # no invented price
    assert "Government" not in json.dumps(d)


def test_share_adds_india_code_to_10_digit_numbers(client, test_env):
    _saree(test_env, "TS-COOPA001")
    for raw in ("9800000001", "09800000001", "+91 98000 00001"):
        url = client.post("/listings/TS-COOPA001/share", json={"to": raw}).json()["share_url"]
        assert url.startswith("https://wa.me/919800000001?text="), (raw, url)


def test_legacy_listing_hides_unfinished_sarees(client, test_env):
    _saree(test_env, "TS-COOPA001", status="failed")
    r = client.get("/listing/TS-COOPA001")
    assert r.status_code == 404 and r.json()["code"] == "LISTING_NOT_READY"
    assert "retaken" in r.json()["message_en"]
    _saree(test_env, "TS-COOPA002", status="processing")
    r = client.get("/listing/TS-COOPA002")
    assert r.status_code == 404 and "being prepared" in r.json()["message_en"]

"""Extra certificate details: weave, close-up, counters, safe image routes, DB upgrade."""
from __future__ import annotations

import io

from sqlalchemy import create_engine, inspect, text

from backend.database import add_missing_columns
from backend.models import Saree
from backend.worker.worker import process_one_job


def _register_and_process(client, test_env, token, sample_image_bytes, qr="TS-COOPA001", extra=None):
    r = client.post(
        "/saree",
        data={"qr_id": qr, "batch_id": "BATCH-A-01", "upload_id": f"upload-{qr}", **(extra or {})},
        files=[("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    process_one_job(test_env["session"])


def test_full_certificate_shows_new_details(client, token_staff_a, test_env, sample_image_bytes):
    _register_and_process(client, test_env, token_staff_a, sample_image_bytes)
    saree = test_env["session"].query(Saree).filter_by(qr_id="TS-COOPA001").first()
    test_env["session"].refresh(saree)
    assert saree.proc_status == "done"
    assert saree.closeup_path and saree.closeup_path.endswith("_window.jpg")
    assert saree.weave_json is not None

    html = client.get("/c/TS-COOPA001?lang=en").text
    assert "threads per inch in total" in html
    assert "Fabric fingerprint recorded" in html
    assert "Not checked by a seller yet." in html
    assert "/c/TS-COOPA001/closeup" in html
    # nothing private leaks
    assert "fingerprints" not in html and "_window.jpg" not in html and ".npz" not in html

    r = client.get("/c/TS-COOPA001/closeup")
    assert r.status_code == 200 and "image/jpeg" in r.headers["content-type"]

    bn = client.get("/c/TS-COOPA001?lang=bn").text
    assert "নিবন্ধিত তাঁতের শাড়ি" in bn


def test_images_hidden_until_done(client):
    # blank tag: no saree yet
    assert client.get("/c/TS-COOPA001/photo").status_code == 404
    assert client.get("/c/TS-COOPA001/closeup").status_code == 404
    assert client.get("/c/TS-NOPE/closeup").status_code == 404


def test_photo_hidden_while_processing(client, token_staff_a, sample_image_bytes):
    client.post(
        "/saree",
        data={"qr_id": "TS-COOPA001", "batch_id": "BATCH-A-01", "upload_id": "upload-q"},
        files=[("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))],
        headers={"Authorization": f"Bearer {token_staff_a}"},
    )
    assert client.get("/c/TS-COOPA001/photo").status_code == 404


def test_old_database_gets_new_columns(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE sarees (qr_id VARCHAR(64) PRIMARY KEY, epi FLOAT)"))
        c.execute(text("INSERT INTO sarees (qr_id, epi) VALUES ('TS-OLD', 50.0)"))
    added = add_missing_columns(eng)
    assert set(added) == {"sarees.weave_json", "sarees.closeup_path", "sarees.spacing_json", "sarees.declared_json", "sarees.listing_json"}
    cols = {c["name"] for c in inspect(eng).get_columns("sarees")}
    assert {"weave_json", "closeup_path", "spacing_json", "declared_json", "epi"} <= cols
    with eng.begin() as c:
        assert c.execute(text("SELECT epi FROM sarees WHERE qr_id='TS-OLD'")).scalar() == 50.0
    assert add_missing_columns(eng) == []  # second run changes nothing


def test_declared_details_saved_and_shown(client, token_staff_a, test_env, sample_image_bytes):
    extra = {"fibre": "Cotton", "dye": "natural", "yarn_count": "80s x 100s", "loom_type": "pit",
             "length_m": "5.5", "days_to_weave": "14", "border": "", "weight_g": ""}
    _register_and_process(client, test_env, token_staff_a, sample_image_bytes, extra=extra)
    html = client.get("/c/TS-COOPA001?lang=en").text
    assert "Declared by the cooperative" in html
    for text in ("Cotton", "Natural dyes", "80s x 100s", "Pit loom", "5.5 m", "14 days"):
        assert text in html, text
    assert "Border (paar)" not in html and "Weight" not in html   # empty fields are left out
    assert "প্রাকৃতিক রং" in client.get("/c/TS-COOPA001?lang=bn").text


def test_no_declared_section_when_nothing_filled(client, token_staff_a, test_env, sample_image_bytes):
    _register_and_process(client, test_env, token_staff_a, sample_image_bytes)
    assert "Declared by the cooperative" not in client.get("/c/TS-COOPA001?lang=en").text


def test_bad_declared_value_rejected_before_saving(client, token_staff_a, test_env, sample_image_bytes):
    for bad in ({"fibre": "plastic"}, {"length_m": "40"}, {"days_to_weave": "2.5"}, {"weight_g": "abc"}):
        r = client.post(
            "/saree",
            data={"qr_id": "TS-COOPA001", "batch_id": "BATCH-A-01", "upload_id": f"u-{list(bad)[0]}", **bad},
            files=[("photos", ("photo.jpg", io.BytesIO(sample_image_bytes), "image/jpeg"))],
            headers={"Authorization": f"Bearer {token_staff_a}"},
        )
        assert r.status_code == 400, bad
        assert r.json()["code"] == "BAD_DETAILS"
        assert r.json()["message_bn"]
    assert test_env["session"].query(Saree).count() == 0   # nothing stored, tag still free


def test_evenness_rows_only_when_reliable(client, token_staff_a, test_env, sample_image_bytes):
    import json as _json
    _register_and_process(client, test_env, token_staff_a, sample_image_bytes)
    s = test_env["session"]
    saree = s.query(Saree).filter_by(qr_id="TS-COOPA001").first()
    saree.spacing_json = _json.dumps({
        "weft": {"cv": 0.183, "n": 333, "expected": 404, "reliable": True},
        "warp": {"cv": 0.197, "n": 82, "expected": 473, "reliable": False},
    })
    s.commit()
    html = client.get("/c/TS-COOPA001?lang=en").text
    assert "Weft rows spacing" in html and "Highly varied" in html and "±18%" in html
    assert "Warp threads spacing" not in html
    saree.spacing_json = _json.dumps({"weft": {"cv": 0.02, "reliable": True}})
    s.commit()
    html = client.get("/c/TS-COOPA001?lang=en").text
    assert "Very even" in html and "±2%" not in html

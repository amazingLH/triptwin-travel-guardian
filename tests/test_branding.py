from pathlib import Path
import tomllib

from triptwin.branding import PRODUCT_TITLE, PRODUCT_ID
from triptwin.exporter import export_trip_files
from triptwin.functional_examples import example_trip
from triptwin.history_media import capture_previews, attach_original_reference
from PIL import Image


def test_public_identity_and_legacy_configuration_are_compatible():
    import app
    assert app.demo.config["title"] == PRODUCT_TITLE
    components = app.demo.config["components"]
    values = [c.get("props", {}).get("value", "") for c in components]
    assert any(PRODUCT_TITLE in v for v in values if isinstance(v, str))
    assert not any("TripTwin" in v for v in values if isinstance(v, str))
    assert any(c.get("props", {}).get("storage_key") == "triptwin_sessions_v1" for c in components)
    config = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["name"] == PRODUCT_ID
    assert config["project"]["scripts"][PRODUCT_ID] == config["project"]["scripts"]["triptwin"]


def test_calendar_export_uses_current_product_identity(tmp_path):
    files = export_trip_files(example_trip("multi"), directory_root=tmp_path)
    content = Path(files[1]).read_text(encoding="utf-8")
    assert "PRODID:-//TuzhengGuard//" in content
    assert "途证哨 仅分析与提醒" in content
    assert "@tuzhengguard" in content
    assert "TripTwin" not in content


def test_old_example_image_restores_current_asset_without_becoming_paid_parse(tmp_path, monkeypatch):
    import app
    old_image = tmp_path / app.SAMPLE_IMAGE_PATH.name
    Image.new("RGB", (100, 100), "white").save(old_image)
    photos = capture_previews([old_image])
    attach_original_reference(photos[0], old_image, app.HISTORY_FILE_SECRET)
    monkeypatch.setattr(app.gr.utils, "get_upload_folder", lambda: str(tmp_path))
    session = {"snapshot": {"trip_state": {"trip_source": "synthetic_example"}, "image_previews": photos}}
    restored = app._restored_history_view(session)
    assert restored[0] == [str(app.SAMPLE_IMAGE_PATH)]
    assert app._is_sample_upload(app._image_paths(restored[0]))

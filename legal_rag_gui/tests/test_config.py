from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from legal_rag_gui.utils.config import SettingsStore


def test_settings_roundtrip(tmp_path):
    store = SettingsStore(path=tmp_path / "config.yaml")
    store.update(openai_api_key="key", theme="light")
    reloaded = SettingsStore(path=tmp_path / "config.yaml")
    assert reloaded.data.openai_api_key == "key"
    assert reloaded.data.theme == "light"

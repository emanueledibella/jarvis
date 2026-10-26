import subprocess
import sys
from pathlib import Path

import pytest

AUDIT = Path(__file__).resolve().parents[1] / "scripts" / "audit-public.py"


def inventory(tmp_path, files):
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic-publication-fixture")
        subprocess.run(["git", "add", "--force", "--", name], cwd=tmp_path, check=True, capture_output=True)
    return subprocess.run([sys.executable, str(AUDIT)], cwd=tmp_path, capture_output=True, text=True)


@pytest.mark.parametrize("filename", [
    "lights.json", "project-root.txt", ".env.production", ".netrc", ".npmrc",
    "backup/Jarvis.app/Contents/Resources/private-resource.txt",
])
def test_publication_rejects_forced_private_configuration_or_native_bundles(tmp_path, filename):
    result = inventory(tmp_path, [filename])
    assert result.returncode != 0 and "private runtime file" in result.stdout
    assert "synthetic-publication-fixture" not in result.stdout + result.stderr


def test_publication_accepts_generic_examples_and_source_json(tmp_path):
    result = inventory(tmp_path, [".env.example", "config/lights.example.json", "web/src/locales/it.json"])
    assert result.returncode == 0, result.stdout + result.stderr

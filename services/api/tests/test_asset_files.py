import unicodedata
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import asset_files


def test_resolve_asset_path_accepts_equivalent_macos_unicode_forms(tmp_path, monkeypatch):
    nfc_root = tmp_path / "작업중" / "assets"
    nfd_root = Path(unicodedata.normalize("NFD", str(nfc_root)))
    nfd_root.mkdir(parents=True)
    image = nfd_root / "그림.png"
    image.touch()
    monkeypatch.setattr(asset_files, "ASSETS_ROOT", nfc_root)

    assert asset_files.resolve_asset_path(str(image)) == image.resolve()


def test_resolve_asset_path_rejects_sibling(tmp_path, monkeypatch):
    root = tmp_path / "assets"
    sibling = tmp_path / "assets-other" / "image.png"
    sibling.parent.mkdir()
    sibling.touch()
    monkeypatch.setattr(asset_files, "ASSETS_ROOT", root)

    with pytest.raises(HTTPException) as exc:
        asset_files.resolve_asset_path(str(sibling))

    assert exc.value.status_code == 403

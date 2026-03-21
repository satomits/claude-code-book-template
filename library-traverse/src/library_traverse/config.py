"""設定ファイル読み込み"""
from pathlib import Path

import yaml


def load_config(path: Path | None = None) -> dict[str, dict[str, str]]:
    """
    config.yaml を読み込み、有効な図書館設定を返す。

    返り値の形式:
        {
          "sagamihara": {"card_number": "...", "password": "..."},
          ...
        }
    """
    if path is None:
        # カレントディレクトリ → スクリプトの2つ上の親 の順で探す
        candidates = [
            Path("config.yaml"),
            Path(__file__).parent.parent.parent / "config.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                path = candidate
                break

    if path is None or not path.exists():
        raise FileNotFoundError(
            "config.yaml が見つかりません。\n"
            "config.yaml.example をコピーして config.yaml を作成し、"
            "利用する図書館の情報を入力してください。"
        )

    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    libraries: dict[str, dict[str, str]] = {}
    for lib_id, creds in (raw.get("libraries") or {}).items():
        if creds and creds.get("card_number") and creds.get("password"):
            libraries[lib_id] = {
                "card_number": str(creds["card_number"]),
                "password": str(creds["password"]),
            }
    return libraries

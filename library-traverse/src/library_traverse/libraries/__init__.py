"""図書館スクレイパーパッケージ"""
from .base import LibraryScraper
from .ebina import EbinaLibrary
from .fujitsu_ilis import SagamiharaLibrary
from .kawasaki import KawasakiLibrary
from .limedio import AtsugiLibrary, KanagawaPrefLibrary, MachidaLibrary, YokohamaLibrary
from .nec_lics_saas import HadanoLibrary, IseharaLibrary
from .nec_lics_xp import YamatoLibrary

# library_id -> スクレイパークラスのマッピング
LIBRARY_REGISTRY: dict[str, type] = {
    "sagamihara": SagamiharaLibrary,
    "kawasaki": KawasakiLibrary,
    "yokohama": YokohamaLibrary,
    "kanagawa_pref": KanagawaPrefLibrary,
    "machida": MachidaLibrary,
    "ebina": EbinaLibrary,
    "hadano": HadanoLibrary,
    "yamato": YamatoLibrary,
    "isehara": IseharaLibrary,
    "atsugi": AtsugiLibrary,
}

__all__ = [
    "LibraryScraper",
    "LIBRARY_REGISTRY",
    "SagamiharaLibrary",
    "KawasakiLibrary",
    "YokohamaLibrary",
    "KanagawaPrefLibrary",
    "MachidaLibrary",
    "EbinaLibrary",
    "HadanoLibrary",
    "YamatoLibrary",
    "IseharaLibrary",
    "AtsugiLibrary",
]

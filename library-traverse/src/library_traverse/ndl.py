"""国立国会図書館サーチAPIを使った著者名補完

NDL SRU API: https://ndlsearch.ndl.go.jp/api/sru
タイトルから著者名を並列HTTPリクエストで取得する。
Playwrightのページ遷移不要なので大幅に高速。
"""
import asyncio
import re
import xml.etree.ElementTree as ET
from typing import Union

import httpx

from .models import LoanItem, ReservationItem

_NDL_SRU = "https://ndlsearch.ndl.go.jp/api/sru"
_SRW_NS = "http://www.loc.gov/zing/srw/"

# CDや演奏記録と判定するキーワード（creatorに含まれる場合はスキップ）
_MUSIC_ROLES = {"ピアノ", "指揮", "バイオリン", "チェロ", "ビオラ", "フルート", "管弦楽団", "交響楽団", "フィルハーモニー"}

# タイトル比較時に除去する装飾記号
_SYMBOL_RE = re.compile(r"[●◎■□▲△▼▽★☆♪♦◆◇＊※〔〕【】]")


def _strip_symbols(title: str) -> str:
    """装飾記号をスペースに置換し、連続スペースを正規化する。

    OPACとNDLで記号の有無・種類が異なる場合のマッチングに使用。
    例: 'JAPAN●MADE' → 'JAPAN MADE'
    """
    title = _SYMBOL_RE.sub(" ", title)
    return re.sub(r"\s+", " ", title).strip()


def _normalize_title(title: str) -> str:
    """OPACタイトルを検索用に正規化する。

    - 省略記号（…）とそれ以降を除去（OPACの表示桁数制限による切り捨て）
    - 末尾の副題区切り「－」を除去（「主題－副題－」形式の末尾）
    - 前後の空白を除去
    """
    for ellipsis in ["…", "..."]:
        idx = title.find(ellipsis)
        if idx >= 0:
            title = title[:idx]
    title = title.rstrip("－")
    return title.strip()


def _query_title(title: str, max_len: int = 20) -> str:
    """検索クエリ用に短縮したタイトルを返す。

    「－」（副題区切り）があれば常に主タイトル部分のみ使う。
    NDLは「主題 : 副題」形式で登録しており、「－」で検索するとヒットしないため。
    「－」がなく長い場合は読点・句点・空白で切り、なければ max_len 文字で切る。
    """
    # 副題区切り「－」があれば主タイトル部分のみ使う
    idx = title.find("－")
    if idx > 0:
        return title[:idx]

    if len(title) <= max_len:
        return title
    for sep in ["、", "。", "　", " ", "：", ":", "〜", "～"]:
        idx = title.find(sep)
        if 0 < idx <= max_len:
            return title[:idx]
    return title[:max_len]


async def _fetch_author(client: httpx.AsyncClient, title: str) -> str:
    """NDL SRU APIでタイトルから著者名を取得する。見つからない場合は空文字。"""
    try:
        normalized = _normalize_title(title)
        query = _strip_symbols(_query_title(normalized))
        resp = await client.get(
            _NDL_SRU,
            params={
                "operation": "searchRetrieve",
                "query": f'title="{query}"',
                "maximumRecords": "20",
                "recordSchema": "dcndl",
            },
            timeout=10.0,
        )
        resp.raise_for_status()
        return _extract_author(resp.text, normalized, query)
    except Exception:
        return ""


def _is_music_record(creators: list[str]) -> bool:
    """creatorにCD・演奏記録特有のキーワードが含まれるか判定する。"""
    for creator in creators:
        for role in _MUSIC_ROLES:
            if role in creator:
                return True
    return False


def _title_matches(ndl_title: str, target_title: str, query_prefix: str) -> bool:
    """NDLタイトルとOPACタイトルが同じ本を指すか判定する。

    - 副題区切り文字の違い（OPAC:「－」、NDL:「 : 」）を吸収
    - 装飾記号の差異（「●」vs「 」など）を吸収して比較
    """
    # 装飾記号を除去して比較
    c_ndl = _strip_symbols(ndl_title)
    c_tgt = _strip_symbols(target_title)
    c_qry = _strip_symbols(query_prefix)

    # 完全一致 or 前方一致（どちらかが他方の前半）
    if c_ndl == c_tgt:
        return True
    if c_ndl.startswith(c_tgt) or c_tgt.startswith(c_ndl):
        return True
    # クエリプレフィックスで両者が始まる（「－」vs「：」の表記揺れを吸収）
    if len(c_qry) >= 4 and c_ndl.startswith(c_qry) and c_tgt.startswith(c_qry):
        return True
    return False


def _extract_author(xml_text: str, target_title: str, query_prefix: str) -> str:
    """XMLレスポンスを解析し、タイトルが一致するレコードの著者名を返す。

    優先順位:
      1. タイトルが明示的にマッチ かつ 音楽レコードでない
      2. 最初の結果のタイトルがクエリプレフィックスで始まる場合のみ fallback 返却
         （クエリが曖昧すぎる場合の誤ヒット防止）

    recordData は string-packed XML なので二段階パースが必要。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return ""

    first_non_music: str = ""
    first_result_starts_with_query: bool = False

    for i, rd in enumerate(root.findall(
        f"{{{_SRW_NS}}}records/{{{_SRW_NS}}}record/{{{_SRW_NS}}}recordData"
    )):
        if not rd.text:
            continue
        try:
            inner = ET.fromstring(rd.text)
        except ET.ParseError:
            continue

        titles = [
            e.text.strip()
            for e in inner.iter()
            if e.tag.split("}")[-1] == "title" and e.text
        ]
        creators = [
            e.text.strip()
            for e in inner.iter()
            if e.tag.split("}")[-1] == "creator" and e.text
        ]
        if not creators:
            continue

        is_music = _is_music_record(creators)
        creator = _clean_creator(creators[0])

        # 最初の結果がクエリと前方一致するかチェック（fallback判定に使用）
        # 装飾記号を除去して比較（OPACとNDLで記号が異なる場合に対応）
        if i == 0:
            c_qry = _strip_symbols(query_prefix)
            if any(_strip_symbols(t).startswith(c_qry) for t in titles):
                first_result_starts_with_query = True

        if not is_music and not first_non_music:
            first_non_music = creator

        # タイトルが明示的にマッチ
        if not is_music and any(_title_matches(t, target_title, query_prefix) for t in titles):
            return creator

    # フォールバック: 最初の結果がクエリと前方一致する場合のみ返す
    # （"ビバリウム"のような短くて曖昧なクエリで誤った著者を返さないための抑制）
    if first_result_starts_with_query:
        return first_non_music
    return ""


def _clean_creator(raw: str) -> str:
    """著者名から余分な情報（役割語、生没年など）を除去して名前だけ返す。

    例:
      "森見登美彦 原作"       → "森見登美彦"
      "山田 太郎, 1950-"     → "山田 太郎"
      "アンディ・ウィアー　著" → "アンディ・ウィアー"
    """
    # 全角スペースを半角に統一してから処理
    raw = raw.replace("\u3000", " ")
    # 役割語（「著」「原作」「編」「訳」など）を除去（空白区切り・スラッシュ・角括弧形式）
    for sep in [" 著", " 原作", " 編", " 訳", " 監修", " 著者", "/著", "／著", " [著]", " [編]", " [訳]"]:
        if sep in raw:
            raw = raw.split(sep)[0]
    # 生没年 "name, XXXX-" 形式を除去
    if ", " in raw:
        raw = raw.split(", ")[0]
    return raw.strip()


async def enrich_authors_via_ndl(
    items: list[Union[LoanItem, ReservationItem]],
) -> None:
    """著者が未設定のアイテムをNDL APIで補完する（並列HTTPリクエスト）。"""
    targets = [item for item in items if not item.author and item.title]
    if not targets:
        return

    async with httpx.AsyncClient(http2=True) as client:
        authors = await asyncio.gather(
            *[_fetch_author(client, item.title) for item in targets]
        )

    for item, author in zip(targets, authors):
        item.author = author

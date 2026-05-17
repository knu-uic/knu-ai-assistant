"""특정 문서의 content 안에서 패턴 주변 raw 텍스트를 dump.

목적: LangSmith에서 사용자가 본 '20112016학년도' 같은 표기가 DB에 실제로
어떻게 저장됐는지 (공백/tilde/zero-width 등) 문자 단위로 확인.

실행:
    docker compose exec app python scripts/dump_doc_around.py --content-keyword "[Sheet: 26-1편성]"
    docker compose exec app python scripts/dump_doc_around.py --content-keyword "교양교과목 편성" --around "학년도"
"""
import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg import sql

from config import DB_URL
from db import _doc_ident, SLUGS


def _visualize(s: str) -> str:
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        cp = ord(ch)
        if ch == " ":
            out.append("·")
        elif ch == "\n":
            out.append("⏎")
        elif ch == "\t":
            out.append("→")
        elif cat.startswith("C") or cp in (0x200B, 0x00A0, 0x202F, 0xFEFF):
            out.append(f"<U+{cp:04X}>")
        else:
            out.append(ch)
    return "".join(out)


def _scan_chars(s: str) -> dict:
    counts: dict[str, int] = {}
    for ch in s:
        cp = ord(ch)
        if ch == "~" or cp in (0x200B, 0x00A0, 0x202F, 0xFEFF):
            key = f"U+{cp:04X} ({unicodedata.name(ch, '?')})"
            counts[key] = counts.get(key, 0) + 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--content-keyword", required=True,
                        help="content LIKE %%keyword%% 로 매칭할 문서 식별자")
    parser.add_argument("--around", default="학년도",
                        help="이 토큰 주변 컨텍스트를 dump (기본: '학년도')")
    parser.add_argument("--radius", type=int, default=40,
                        help="앞뒤 출력 글자 수 (기본 40)")
    parser.add_argument("--max-matches", type=int, default=20,
                        help="문서당 최대 출력 매치 수 (기본 20)")
    args = parser.parse_args()

    pat = f"%{args.content_keyword}%"
    hits = 0
    with psycopg.connect(DB_URL) as conn:
        for slug in SLUGS:
            q = sql.SQL(
                "SELECT url, title, content FROM {doc} WHERE content LIKE %s"
            ).format(doc=_doc_ident(slug))
            try:
                rows = conn.execute(q, (pat,)).fetchall()
            except Exception as e:
                print(f"[skip {slug}] {e}")
                continue

            for url, title, content in rows:
                hits += 1
                print("=" * 70)
                print(f"[{slug}] {title}")
                print(f"  url: {url}")
                print(f"  len(content)={len(content)}")

                susp = _scan_chars(content)
                if susp:
                    print(f"  의심 문자 카운트: {susp}")
                else:
                    print(f"  의심 문자 (~, NBSP, ZWSP 등) 없음")

                matches = list(re.finditer(re.escape(args.around), content))
                print(f"  '{args.around}' 매치 수: {len(matches)}")
                for i, m in enumerate(matches[: args.max_matches], 1):
                    start = max(0, m.start() - args.radius)
                    end = min(len(content), m.end() + args.radius)
                    raw = content[start:end]
                    print(f"  --- match {i} (offset={m.start()}) ---")
                    print(f"  raw : {raw!r}")
                    print(f"  view: {_visualize(raw)}")

    if hits == 0:
        print(f"매칭 문서 없음 (content LIKE '{args.content_keyword}').")
        return 1
    print(f"\n[done] {hits}개 문서 dump.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

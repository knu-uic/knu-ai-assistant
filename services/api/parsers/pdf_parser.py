"""PDF 바이트 → opendataloader-pdf(ODL) 마크다운 추출 공유 헬퍼.

커리큘럼 파서와 첨부파일 추출기가 공유한다.

ODL은 파일 입출력 + JVM 서브프로세스(convert 반환값 None)라서, 임시 디렉터리에
PDF를 쓰고 결과 .md를 읽어 돌려준다. 이미지 추출은 항상 끈다(image_output="off"):
스캔본에서 ![](path) 이미지 링크 수프가 나오면 호출측의 "빈 문자열 → OCR 폴백"
판정이 깨지기 때문이다(스캔본은 빈 문자열을 반환해야 한다).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import opendataloader_pdf


def parse_pdf(
    data: bytes,
    markdown_with_html: bool = False,
    page_separator: str | None = None,
) -> str:
    """PDF 바이트를 ODL 마크다운으로 변환해 반환한다.

    - markdown_with_html=True: 표를 HTML <table>(rowspan/colspan 무손실)로 임베드.
      False: 순수 마크다운 표로 출력.
    - page_separator: 지정 시 페이지 사이에 이 문자열을 넣는다(호출측이 split해 페이지 단위 처리).
    - 텍스트 레이어가 없는 스캔본은 빈/공백 문자열을 반환한다(호출측 OCR 폴백 트리거).
    """
    with tempfile.TemporaryDirectory(prefix="odl-pdf-") as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / "input.pdf"
        input_path.write_bytes(data)
        out_dir = tmp_dir / "out"
        out_dir.mkdir()

        opendataloader_pdf.convert(
            input_path=[str(input_path)],
            output_dir=str(out_dir),
            format="markdown",
            markdown_with_html=markdown_with_html,
            markdown_page_separator=page_separator,
            image_output="off",
            quiet=True,
        )

        mds = sorted(out_dir.rglob("*.md"))
        return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in mds).strip()

"""공주대 공지 첨부파일/본문 이미지 → 텍스트 변환 어댑터.

각 어댑터는 실패 시 빈 문자열 또는 [실패 사유]를 돌려준다.
호출자는 결과를 본문에 그대로 이어 붙이면 된다.
"""
from model import get_llm

# --- 표준 라이브러리 ---
import io           # 바이트 데이터를 "파일처럼" 다루기 위한 BytesIO 용도 (pdfplumber/openpyxl/zipfile이 파일객체를 요구함)
import base64       # 이미지 바이트를 Gemini에 보낼 때 base64 문자열로 인코딩
import zipfile      # HWPX 파일은 사실상 ZIP 컨테이너라서 직접 열어서 내부 XML을 꺼냄
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path                       # 파일 확장자(.pdf, .hwpx 등) 추출용
from typing import Any
from xml.etree import ElementTree as ET        # HWPX 내부 XML 파싱

# --- 외부 라이브러리 ---
import pdfplumber                              # PDF에서 텍스트 추출 (텍스트 PDF용)
import openpyxl                                # XLSX 읽기 (현재 라우터에서는 미사용)
import xlrd                                    # XLS 읽기
from langchain_core.messages import HumanMessage          # LangChain 멀티모달 메시지 포맷


# HWPX 본문(paragraph)의 XML 네임스페이스.
# 이 prefix를 붙여야 ElementTree가 <hp:t> 같은 텍스트 노드를 찾을 수 있다.
_HWPX_PARA_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_SUPPORTED_ZIP_EXTS = {".zip", ".pdf", ".hwpx", ".hwp", ".xlsx", ".xls", ".jpg", ".jpeg", ".png", ".gif"}
_MAX_ZIP_MEMBERS = 30
_MAX_ZIP_DEPTH = 2
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def hwpx_bytes_to_text(data: bytes) -> str:
    """hwpx 패키지(ZIP)의 Contents/section*.xml에서 <hp:t> 텍스트 노드를 모두 추출.

    표/일정/문의처까지 텍스트로 들어있다. 이미지는 누락되지만 RAG 입력에는 충분.
    """
    parts = []  # 모든 section에서 모은 텍스트 조각을 담을 버퍼

    # bytes를 파일처럼 감싸서 ZipFile에 넘긴다 (디스크에 저장하지 않고 메모리에서 처리)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        # HWPX 내부 구조: Contents/section0.xml, section1.xml, ... 식으로 본문이 분할 저장돼 있음
        # 페이지 순서를 맞추기 위해 정렬해서 순회한다
        names = sorted(
            n for n in z.namelist()
            if n.startswith("Contents/section") and n.endswith(".xml")
        )
        for name in names:
            # 해당 section XML을 읽어 트리로 파싱
            root = ET.fromstring(z.read(name))
            # <hp:t> = HWPX의 "text run" 노드. 실제 글자가 담긴 leaf 노드만 골라낸다
            for t in root.iter(f"{_HWPX_PARA_NS}t"):
                if t.text:  # 빈 노드는 스킵
                    parts.append(t.text)

    # 줄바꿈으로 이어붙여 단일 문자열로 반환 (앞뒤 공백 정리)
    return "\n".join(parts).strip()


# VLM(Gemini)에게 OCR을 시킬 때 쓰는 고정 프롬프트.
# "설명 문장 붙이지 마라"가 핵심 — 안 그러면 "이 이미지는 ~에 대한 안내입니다" 같은 군더더기가 본문에 섞임.
_VLM_PROMPT = """이 이미지는 대학 공지글의 일부다. 이미지에 적힌 모든 텍스트와 표를 한국어 plain text로 빠짐없이 추출하라.
원칙:
- 설명, 분석, 추론, 생각 과정 출력 절대 금지.
- 행사명, 일정, 신청기한, 신청방법, 문의처 등 정보 항목은 누락 없이 그대로 옮긴다.
- 표는 줄바꿈으로 항목을 구분한다.
- 장식/광고 문구도 모두 포함한다.
- 텍스트만 출력하고 설명 문장은 붙이지 않는다."""


def _image_to_text(image_bytes: bytes, mime: str) -> str:
    """이미지 바이트를 Gemini에 던져 텍스트만 받아오는 저수준 헬퍼."""
    # Gemini 멀티모달 API는 data URL 형태(base64 인코딩)로 이미지를 받는다
    b64 = base64.b64encode(image_bytes).decode()

    # LangChain의 멀티모달 메시지: 텍스트 블록 + 이미지 블록을 한 메시지에 같이 넣는다
    msg = HumanMessage(content=[
        {"type": "text", "text": _VLM_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ])

    resp = get_llm().invoke([msg])
    # resp.content가 가끔 list-of-blocks 형태로 올 때가 있어서 방어적으로 문자열화
    return resp.content if isinstance(resp.content, str) else str(resp.content)


def _download(
    url: str,
    context,
    referer: str | None = None,
    detail_page=None,
    attachment_selector: str | None = None,
    attachment_index: int | None = None,
) -> bytes:
    """실제 Chromium 다운로드 경로를 사용해 첨부파일을 가져온다."""
    created_page = detail_page is None
    page = detail_page or context.new_page()

    lower_url = url.lower()

    direct_extensions = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
        ".pdf",
        ".txt",
        ".csv",
    )

    try:
        # 이미지/JPG/PDF 같은 직접 파일 URL은 browser download 이벤트 대신
        # HTTP request로 바로 가져오는 편이 훨씬 안정적이다.
        if any(lower_url.endswith(ext) for ext in direct_extensions):
            try:
                response = context.request.get(
                    url,
                    timeout=int(
                        os.getenv("ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS", "120000")
                    ),
                    fail_on_status_code=False,
                )

                if response.ok:
                    return response.body()

            except Exception as e:
                print(f"[direct request failed] {url} -> {e}")
        # 일부 학교 사이트는 Referer 세션이 없으면 download.do 연결 자체를 끊는다.
        if detail_page and attachment_selector is not None and attachment_index is not None:
            attachments = page.locator(attachment_selector)

            target = attachments.nth(attachment_index)

            timeout_ms = int(
                os.getenv("ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS", "120000")
            )

            with page.expect_download(timeout=timeout_ms) as download_info:
                target.locator('a[href*="download.do"]').first.click(
                    timeout=5000,
                    no_wait_after=True,
                )

        elif referer:
            timeout_ms = int(
                os.getenv("ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS", "120000")
            )
            download_selectors = [
                f'a[href="{url}"]',
                f'a[href*="download.do"]',
                'a[download]',
                'button[onclick*="download"]',
                'a[onclick*="download"]',
            ]

            clicked = False

            for selector in download_selectors:
                try:
                    target = page.locator(selector).first

                    if target.count() == 0:
                        continue

                    with page.expect_download(timeout=timeout_ms) as download_info:
                        target.click(
                            timeout=5000,
                            no_wait_after=True,
                        )

                    clicked = True
                    break

                except Exception:
                    continue

            if not clicked:
                raise RuntimeError(
                    f"다운로드 버튼을 찾지 못했습니다: {url}"
                )

        else:
            timeout_ms = int(
                os.getenv("ATTACHMENT_DOWNLOAD_TIMEOUT_SECONDS", "120000")
            )
            with page.expect_download(timeout=timeout_ms) as download_info:
                page.goto(url, wait_until="commit", timeout=timeout_ms)

        download = download_info.value

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            temp_path = tmp.name

        download.save_as(temp_path)

        data = Path(temp_path).read_bytes()

        try:
            os.remove(temp_path)
        except Exception:
            pass

        return data

    except Exception as e:
        print(f"[download failed] {url} -> {e}")
        return b""

    finally:
        if created_page:
            try:
                page.close()
            except Exception:
                pass


def pdf_to_text(data: bytes) -> str:
    """텍스트 PDF용 1차 추출. 스캔 PDF는 빈 문자열을 반환한다."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        # 페이지마다 텍스트를 뽑아 정리. extract_text가 None을 줄 수 있어 or ""로 방어.
        pages = [(p.extract_text() or "").strip() for p in pdf.pages]
    return "\n".join(pages).strip()


def _pdf_bytes_full(data: bytes) -> str:
    """pdfplumber 1차 → 비어있으면 pdf2image+VLM fallback."""
    body = pdf_to_text(data)
    if body:
        # 텍스트 레이어가 있는 정상 PDF: 1차 결과를 그대로 사용
        return body

    # 여기 도달했다는 건 "스캔본 PDF" = 이미지 덩어리. 페이지를 렌더링해서 OCR로 돌린다.
    # pdf2image는 무거운 의존성이라 폴백 경로에서만 lazy import.
    from pdf2image import convert_from_bytes
    images = convert_from_bytes(data, dpi=150)  # 150dpi면 OCR 품질과 속도의 합리적 절충

    chunks = []
    for im in images:
        # PIL 이미지를 PNG 바이트로 직렬화 → VLM에 전달
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        chunks.append(_image_to_text(buf.getvalue(), "image/png"))
    return "\n".join(chunks).strip()


def _find_soffice() -> str | None:
    configured = os.getenv("LIBREOFFICE_BIN")
    candidates = [
        configured,
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    return next((c for c in candidates if c and Path(c).exists()), None)


def run_soffice_convert(input_path: Path, out_dir: Path, page_range: str | None = None) -> Path | None:
    soffice = _find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice(soffice)를 찾을 수 없습니다. LIBREOFFICE_BIN을 설정하세요.")

    convert_to = "pdf:writer_pdf_Export"
    if page_range:
        options = {"PageRange": {"type": "string", "value": page_range}}
        convert_to = f"{convert_to}:{json.dumps(options, separators=(',', ':'))}"

    cmd = [
        soffice,
        "--headless",
        "--nologo",
        "--nofirststartwizard",
        "--nodefault",
        "--norestore",
        "--convert-to",
        convert_to,
        input_path.name,
        "--outdir",
        str(out_dir.resolve()),
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=input_path.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=int(os.getenv("LIBREOFFICE_TIMEOUT_SECONDS", "90")),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    pdf_path = out_dir / f"{input_path.stem}.pdf"
    return pdf_path if pdf_path.exists() and pdf_path.stat().st_size > 0 else None


def _hwp_ole_strings_to_text(data: bytes) -> str:
    """LibreOffice 변환 실패 시 HWP 5.x 내부 UTF-16LE 문자열을 최대한 회수."""
    decoded = data.decode("utf-16le", "ignore")
    runs: list[str] = []
    pattern = r"[\uAC00-\uD7A3A-Za-z0-9\s().,/%·\-:]{3,}"
    for match in re.finditer(pattern, decoded):
        text = " ".join(match.group(0).split())
        if any("가" <= ch <= "힣" for ch in text):
            runs.append(text)

    extracted = "\n".join(dict.fromkeys(runs))
    meta_markers = ["표 및 글자", "문단모양 등의 변경 금지"]
    cut_points = [extracted.find(marker) for marker in meta_markers if marker in extracted]
    if cut_points:
        extracted = extracted[:min(cut_points)].rstrip()
    return extracted


def _office_pdf_text(data: bytes, filename: str) -> str:
    """오피스 문서(HWP/HWPX 등)를 LibreOffice로 PDF 변환 후 텍스트 추출. 실패 시 "".
    전체 변환 → 실패하면 페이지 단위 프로빙. hwp·hwpx 폴백 경로에서 공유한다.
    스캔본은 _pdf_bytes_full 내부에서 pdf2image+VLM로 처리된다."""
    suffix = Path(filename).suffix or ".hwp"
    with tempfile.TemporaryDirectory(prefix="office-convert-") as tmp:
        tmp_dir = Path(tmp)
        input_path = tmp_dir / f"input{suffix}"
        input_path.write_bytes(data)
        full_dir = tmp_dir / "full"
        full_dir.mkdir()

        pdf_path = run_soffice_convert(input_path, full_dir)
        if pdf_path:
            return _pdf_bytes_full(pdf_path.read_bytes())

        page_texts: list[str] = []
        max_pages = int(os.getenv("HWP_CONVERT_MAX_PAGE_PROBES", "3"))
        empty_streak = 0
        for page_no in range(1, max_pages + 1):
            page_dir = tmp_dir / f"page-{page_no}"
            page_dir.mkdir()
            page_pdf = run_soffice_convert(input_path, page_dir, str(page_no))
            if not page_pdf:
                empty_streak += 1
                if empty_streak >= 3:
                    break
                continue

            text = _pdf_bytes_full(page_pdf.read_bytes()).strip()
            if text:
                page_texts.append(text)
                empty_streak = 0
            else:
                empty_streak += 1
                if empty_streak >= 3:
                    break

        if page_texts:
            return "\n\n".join(page_texts).strip()

    return ""


def hwp_bytes_to_text(data: bytes, filename: str = "attachment.hwp") -> str:
    """HWP(5.x)를 LibreOffice→PDF로 텍스트화. 실패 시 OLE 내부 문자열 회수."""
    text = _office_pdf_text(data, filename)
    if text:
        return text

    # 최후수단: HWP5 OLE 바이너리 내부 UTF-16 문자열 직접 회수(hwp 전용).
    fallback = _hwp_ole_strings_to_text(data)
    if fallback:
        return fallback

    raise RuntimeError("LibreOffice HWP→PDF 변환 실패")


def _preview_failed(text: str) -> bool:
    """synapView 미리보기 결과가 "실패"인지 판정."""
    if not text:
        return True
    # 공주대 synapView는 변환 실패 시 페이지에 안내 문구를 그대로 박아둔다 → 텍스트로 잡힘
    if "변환이 실패" in text or "변환에 실패" in text:
        return True
    # preview가 일부만 로드되어도 fallback 없이 우선 사용한다.
    # 대형 HWP(수백 페이지)는 synapView 전체 렌더가 매우 느려
    # 제목/일부 본문만 먼저 도착하는 경우가 많다.
    # 완전 빈 문자열 수준일 때만 실패로 본다.
    return len(text.strip()) < 5


def _zip_member_text(
    member_name: str,
    data: bytes,
    source_url: str,
    context,
    include_xlsx: bool,
    depth: int,
) -> str:
    ext = Path(member_name.lower()).suffix
    label = f"[압축 내부 파일: {member_name}]"

    if ext == ".zip":
        nested = _zip_bytes_to_text(data, source_url, context, include_xlsx, depth + 1)
        return f"{label}\n{nested}" if nested else f"{label}\n(압축 내부 텍스트 없음)"

    if ext == ".pdf":
        return f"{label}\n{_pdf_bytes_full(data)}"

    if ext == ".hwpx":
        return f"{label}\n{hwpx_bytes_to_text(data)}"

    if ext == ".hwp":
        return f"{label}\n{hwp_bytes_to_text(data, member_name)}"

    if ext == ".xlsx":
        if include_xlsx:
            return f"{label}\n{xlsx_to_text(data)}"
        return f"{label}\n(엑셀 첨부 — 임베딩 제외. 원본 ZIP: {source_url})"

    if ext == ".xls":
        if include_xlsx:
            return f"{label}\n{xls_to_text(data)}"
        return f"{label}\n(엑셀 첨부 — 임베딩 제외. 원본 ZIP: {source_url})"

    if ext in _IMAGE_EXTS:
        mime = "image/png" if ext == ".png" else "image/jpeg"
        return f"{label}\n{_image_to_text(data, mime).strip()}"

    return f"{label}\n(지원하지 않는 압축 내부 확장자, 건너뜀)"


def _zip_bytes_to_text(data: bytes, source_url: str, context, include_xlsx: bool, depth: int = 0) -> str:
    if depth > _MAX_ZIP_DEPTH:
        return "(ZIP 중첩 깊이 제한으로 내부 압축 해제 중단)"

    parts: list[str] = []
    if not data:
        return "(빈 ZIP 데이터)"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members = [
            info for info in z.infolist()
            if not info.is_dir()
            and "__MACOSX/" not in info.filename
            and not Path(info.filename).name.startswith(".")
        ]
        handled = 0
        for info in members:
            if handled >= _MAX_ZIP_MEMBERS:
                parts.append(f"(ZIP 내부 파일 {len(members)}개 중 {_MAX_ZIP_MEMBERS}개만 처리)")
                break

            ext = Path(info.filename.lower()).suffix
            if ext not in _SUPPORTED_ZIP_EXTS:
                continue

            handled += 1
            try:
                parts.append(
                    _zip_member_text(
                        info.filename,
                        z.read(info),
                        source_url,
                        context,
                        include_xlsx,
                        depth,
                    )
                )
            except Exception as e:
                parts.append(f"[압축 내부 파일: {info.filename}]\n(처리 실패: {e})")

    return "\n\n".join(part for part in parts if part.strip()).strip()


# XLSX 첨부는 노이즈가 많아 기본은 임베딩 제외. 단 아래 키워드가 제목/본문에 보이면 활성화.
# 수강신청·교양·교과목 편성 같은 표 데이터가 핵심인 공지에서만 켜진다.
XLSX_KEYWORDS = ("교양", "수강신청", "교과목", "편성", "시간표", "강의계획", "개설")


def _trim_empty_tail(cells: list[str]) -> list[str]:
    """오른쪽 끝 빈 셀 제거. 엑셀은 사용 범위가 넓게 잡히는 일이 많다."""
    end = len(cells)
    while end > 0 and not cells[end - 1].strip():
        end -= 1
    return cells[:end]


def _looks_numeric_or_code(value: str) -> bool:
    s = value.strip().replace(",", "")
    if not s:
        return False
    if s.replace(".", "", 1).isdigit():
        return True
    # 2026-1, 3-3-0, 2009094 같은 학기/학점/코드형 값.
    compact = s.replace("-", "").replace(".", "").replace("/", "")
    return compact.isdigit()


def _looks_like_header(row: list[str], next_rows: list[list[str]]) -> bool:
    non_empty = [c.strip() for c in row if c.strip()]
    if len(non_empty) < 2:
        return False

    following_width = max(
        (sum(1 for c in r if c.strip()) for r in next_rows),
        default=0,
    )
    if following_width < 2:
        return False

    unique_ratio = len(set(non_empty)) / len(non_empty)
    textish_ratio = sum(not _looks_numeric_or_code(c) for c in non_empty) / len(non_empty)
    avg_len = sum(len(c) for c in non_empty) / len(non_empty)

    return unique_ratio >= 0.7 and textish_ratio >= 0.55 and avg_len <= 40


def _dedupe_headers(row: list[str]) -> list[str]:
    headers = []
    seen: dict[str, int] = {}
    for idx, cell in enumerate(row):
        base = cell.strip() or f"열{idx + 1}"
        seen[base] = seen.get(base, 0) + 1
        headers.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return headers


def xlsx_relevant(*texts: str) -> bool:
    """제목·본문 등을 합쳐 XLSX_KEYWORDS 중 하나라도 포함하면 True."""
    blob = "\n".join(t for t in texts if t)
    return any(kw in blob for kw in XLSX_KEYWORDS)


def xlsx_to_text(data: bytes) -> str:
    """XLSX 시트를 검색 친화적인 텍스트로 직렬화.

    표 헤더는 [표 헤더]로 표시하고, 데이터 행은 [행] 값 나열로 둔다.
    청킹 단계(embed.py)가 표 안에서 잘린 chunk 앞에 현재 헤더를 다시
    붙여주므로, 여기서는 행마다 컬럼명을 반복하지 않는다.
    """
    # data_only=True: 수식(=A1+B1) 대신 마지막으로 계산된 값을 가져옴
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    out = []
    for sheet in wb.worksheets:
        out.append(f"[Sheet: {sheet.title}]")  # 시트 경계 표시
        headers: list[str] | None = None
        rows = []
        for row in sheet.iter_rows(values_only=True):
            # None은 빈 문자열로, 나머지는 str로 일괄 변환
            cells = _trim_empty_tail(["" if v is None else str(v).strip() for v in row])
            # 완전히 빈 행은 스킵 (엑셀에 흔한 공백 행 제거)
            if any(c.strip() for c in cells):
                rows.append(cells)

        for idx, row in enumerate(rows):
            if headers is None and _looks_like_header(row, rows[idx + 1:idx + 4]):
                headers = _dedupe_headers(row)
                out.append("[표 헤더] " + " | ".join(headers))
                continue

            if headers:
                row_text = " | ".join(c for c in row if c)
                if not row_text:
                    continue
                out.append("[행] " + row_text)
            else:
                out.append(" | ".join(c for c in row if c))
        out.append(f"[End Sheet: {sheet.title}]")
    return "\n".join(out).strip()


def xls_to_text(data: bytes) -> str:
    """구형 XLS 시트를 검색 친화적인 텍스트로 직렬화."""
    book = xlrd.open_workbook(file_contents=data)
    out = []
    for sheet in book.sheets():
        out.append(f"[Sheet: {sheet.name}]")
        headers: list[str] | None = None
        rows = []
        for r in range(sheet.nrows):
            cells = _trim_empty_tail([
                "" if sheet.cell_value(r, c) is None else str(sheet.cell_value(r, c)).strip()
                for c in range(sheet.ncols)
            ])
            if any(c.strip() for c in cells):
                rows.append(cells)

        for idx, row in enumerate(rows):
            if headers is None and _looks_like_header(row, rows[idx + 1:idx + 4]):
                headers = _dedupe_headers(row)
                out.append("[표 헤더] " + " | ".join(headers))
                continue

            row_text = " | ".join(c for c in row if c)
            if row_text:
                out.append(("[행] " if headers else "") + row_text)
        out.append(f"[End Sheet: {sheet.name}]")
    return "\n".join(out).strip()


def _office_preview_fallback(att: dict, context) -> str:
    preview_url = att.get("preview_url")

    if not preview_url:
        return ""

    try:
        text = hwp_via_preview(preview_url, context)

        # viewer에서 일부 텍스트라도 확보되면 그대로 사용한다.
        # 공주대처럼 download.do는 막혀 있지만 synapView 렌더는 허용하는
        # 사이트가 있어 preview 텍스트를 우선 신뢰한다.
        return text or ""

    except Exception as e:
        print(f"[preview fallback failed] {preview_url} -> {e}")
        return ""


def hwp_via_preview(preview_url: str, context) -> str:
    """synapView 전체 스크롤 기반 텍스트 추출.

    synapView는 대형 HWP/HWPX를 lazy rendering 하는 경우가 많아
    단순 body 추출만으로는 앞부분 일부만 수집된다.
    따라서 viewer를 끝까지 스크롤하며 iframe 텍스트 변화를 반복 수집한다.
    """
    page = context.new_page()

    try:
        try:
            page.goto(
                preview_url,
                wait_until="domcontentloaded",
                timeout=int(os.getenv("HWP_PREVIEW_TIMEOUT_MS", "45000")),
            )
        except Exception as e:
            # synapView는 timeout 이후에도 iframe 렌더가 계속 진행되는 경우가 많다.
            # 따라서 timeout을 치명적 실패로 보지 않고 계속 스크롤 수집을 시도한다.
            print(f"[synap goto timeout ignored] {e}")

        page.wait_for_timeout(
            int(os.getenv("HWP_PREVIEW_EXTRA_WAIT_MS", "10000"))
        )

        max_scrolls = int(os.getenv("HWP_PREVIEW_MAX_SCROLLS", "1200"))
        scroll_px = int(os.getenv("HWP_PREVIEW_SCROLL_PX", "4000"))
        settle_ms = int(os.getenv("HWP_PREVIEW_SCROLL_WAIT_MS", "3500"))
        stable_limit = int(os.getenv("HWP_PREVIEW_STABLE_LIMIT", "30"))

        collected_chunks: list[str] = []
        seen_texts: set[str] = set()

        stable_count = 0
        viewer_selectors = [
            ".viewer",
            "#viewer",
            ".doc-view",
            ".synap-viewer",
            ".document-view",
            ".viewer-container",
        ]
        last_total_len = 0

        def collect_frame_texts() -> int:
            total = 0

            for frame in page.frames:
                try:
                    text = frame.inner_text("body").strip()
                except Exception:
                    continue

                if not text:
                    continue

                normalized = "\n".join(
                    line.strip()
                    for line in text.splitlines()
                    if line.strip()
                )

                if not normalized:
                    continue

                total += len(normalized)

                if normalized not in seen_texts:
                    seen_texts.add(normalized)
                    collected_chunks.append(normalized)

            return total

        # 초기 수집
        last_total_len = collect_frame_texts()

        for _ in range(max_scrolls):
            scrolled = False

            for selector in viewer_selectors:
                try:
                    locator = page.locator(selector).first

                    if locator.count() == 0:
                        continue

                    locator.evaluate(
                        "(el, y) => el.scrollBy(0, y)",
                        scroll_px,
                    )

                    scrolled = True
                    break

                except Exception:
                    continue

            # viewer container를 못 찾으면 body wheel fallback
            if not scrolled:
                try:
                    page.mouse.wheel(0, scroll_px)
                except Exception:
                    pass

            page.wait_for_timeout(settle_ms)

            current_total_len = collect_frame_texts()

            # 더 이상 텍스트 증가가 없으면 안정화 카운트 증가
            if current_total_len <= last_total_len:
                stable_count += 1
            else:
                stable_count = 0
                last_total_len = current_total_len

            # 여러 번 연속 변화 없으면 종료
            if stable_count >= stable_limit:
                break

        print(
            f"[synap collected] chunks={len(collected_chunks)} chars={sum(len(c) for c in collected_chunks)}"
        )
        merged = "\n\n".join(collected_chunks).strip()

        # 너무 긴 중복 제거
        lines = []
        seen_lines = set()

        for line in merged.splitlines():
            normalized = line.strip()

            if not normalized:
                continue

            if normalized in seen_lines:
                continue

            seen_lines.add(normalized)
            lines.append(normalized)

        return "\n".join(lines).strip()

    finally:
        try:
            page.close()
        except Exception:
            pass


def inline_image_to_text(
    image_url: str,
    context,
) -> tuple[str, bytes | None, str | None]:
    """본문 inline 이미지를 VLM으로 텍스트화.

    반환: (text, raw_bytes, mime)
      - 다운로드 실패: ("", None, None)
      - 다운로드 성공/VLM 실패: ("", raw_bytes, mime)  — bytes는 보존
    """
    # 1단계: 이미지 다운로드. 실패하면 더 진행할 의미가 없으니 즉시 빈 결과 반환.
    try:
        data = _download(image_url, context)
    except Exception:
        return "", None, None

    # 확장자 기반의 단순 mime 추정. (정확도가 필요하면 magic number 검사로 바꿔야 함)
    mime = "image/png" if image_url.lower().endswith(".png") else "image/jpeg"

    # 2단계: VLM 호출. 실패해도 raw_bytes는 살려둬서 호출자가 재처리할 수 있게 한다.
    try:
        text = _image_to_text(data, mime).strip()
    except Exception:
        text = ""

    return text, data, mime


def attachment_to_text(att: dict, context, include_xlsx: bool = False):
    """att = {'filename', 'download_url', 'preview_url' | None}.

    include_xlsx: 기본 False. True면 XLSX 본문도 추출해 임베딩 대상에 포함.
                  호출자(crawler)가 xlsx_relevant(title, body)로 판정해 전달.

    반환: (text, asset_meta)
      text: '[첨부: <파일명>]\\n<본문>' (기존 호환, 실패 시 본문 자리에 사유)
      asset_meta: {
        kind: inline_image | attachment_image | attachment_pdf
              | attachment_hwpx | attachment_xlsx | attachment_other,
        filename, source_url, mime_type,
        raw_bytes: bytes | None,  — attachment_image일 때만 채워짐
        extracted_text: str
      }
    """
    # 입력 unpack
    name = att["filename"]
    ext = Path(name.lower()).suffix       # .pdf / .hwpx / .jpg ... — 소문자 통일 후 확장자 추출
    label = f"[첨부: {name}]"             # 본문 앞에 붙일 라벨 (RAG 컨텍스트에서 출처 식별용)
    source_url = att["download_url"]

    if not source_url:
        body = "(첨부 다운로드 URL 없음)"
        meta = {
            "kind": "attachment_other",
            "filename": name,
            "source_url": source_url,
            "mime_type": None,
            "raw_bytes": None,
            "extracted_text": body,
        }
        return f"{label}\n{body}", meta

    # 메타 기본값을 먼저 깔아두고, 아래 분기에서 필드를 덮어쓰는 패턴
    meta = {
        "kind": "attachment_other",
        "filename": name,
        "source_url": source_url,
        "mime_type": None,
        "raw_bytes": None,
        "extracted_text": "",
    }

    # try 전체로 감싸서 어떤 분기에서 예외가 나더라도 "(처리 실패: ...)" 문자열로 환원한다
    # → 호출자(crawler)는 예외 처리 없이 결과를 본문에 그대로 이어붙일 수 있다
    try:
        # ───────── 분기 1: PDF ─────────
        if ext == ".pdf":
            meta["kind"] = "attachment_pdf"
            meta["mime_type"] = "application/pdf"
            data = _download(source_url, context)
            body = _pdf_bytes_full(data)   # 텍스트 1차 → 실패 시 이미지 OCR 폴백 (위 함수 참고)

        # ───────── 분기 2: 엑셀 ─────────
        elif ext in (".xlsx", ".xls"):
            meta["kind"] = "attachment_xlsx"
            meta["mime_type"] = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if ext == ".xlsx" else "application/vnd.ms-excel"
            )
            if include_xlsx and ext == ".xlsx":
                # 키워드 매칭(수강신청·교양·편성 등)이 걸린 공지 → 표 전체를 텍스트화해서 임베딩 대상에 포함.
                try:
                    data = _download(source_url, context)
                    body = xlsx_to_text(data)
                except Exception:
                    body = _office_preview_fallback(att, context)
                    if not body:
                        raise
            elif include_xlsx and ext == ".xls":
                try:
                    data = _download(source_url, context)
                    body = xls_to_text(data)
                except Exception:
                    body = _office_preview_fallback(att, context)
                    if not body:
                        raise
            else:
                # 기본: 노이즈 많은 엑셀은 임베딩 제외하고 안내문만 남김.
                body = f"(엑셀 첨부 — 임베딩 제외. 원본 다운로드: {source_url})"

        # ───────── 분기 3: HWPX / HWP ─────────
        elif ext in (".hwpx", ".hwp"):
            meta["kind"] = "attachment_hwpx"
            meta["mime_type"] = (
                "application/vnd.hancom.hwpx" if ext == ".hwpx" else "application/x-hwp"
            )
            body = ""

            # 1차 시도: synapView 미리보기 페이지에서 텍스트 긁기
            body = _office_preview_fallback(att, context)

            # preview가 완전히 비어있을 때만 원본 다운로드 fallback 수행
            if not body or not body.strip():
                if ext == ".hwpx":
                    # .hwpx는 ZIP 구조라 직접 까서 XML 텍스트 노드를 뽑을 수 있다
                    file_data = _download(
                        source_url,
                        context,
                        referer=att.get("preview_url") or source_url,
                        detail_page=att.get("detail_page"),
                        attachment_selector=att.get("attachment_selector"),
                        attachment_index=att.get("attachment_index"),
                    )

                    if not file_data:
                        body = body or "(원본 HWPX 다운로드 실패)"
                    else:
                        body = hwpx_bytes_to_text(file_data)
                else:
                    # .hwp는 LibreOffice headless로 PDF 변환 후 기존 PDF 텍스트/OCR 파이프라인에 태운다.
                    file_data = _download(
                        source_url,
                        context,
                        referer=att.get("preview_url") or source_url,
                        detail_page=att.get("detail_page"),
                        attachment_selector=att.get("attachment_selector"),
                        attachment_index=att.get("attachment_index"),
                    )

                    if not file_data:
                        body = body or "(원본 HWP 다운로드 실패)"
                    else:
                        body = hwp_bytes_to_text(file_data, name)

        # ───────── 분기 4: 이미지 첨부 ─────────
        elif ext in _IMAGE_EXTS:
            meta["kind"] = "attachment_image"
            meta["mime_type"] = "image/png" if ext == ".png" else "image/jpeg"
            data = _download(source_url, context)
            meta["raw_bytes"] = data       # 멀티모달 임베딩/재처리를 위해 원본 바이트도 보존
            body = _image_to_text(data, meta["mime_type"]).strip()

        # ───────── 분기 5: ZIP ─────────
        elif ext == ".zip":
            meta["kind"] = "attachment_zip"
            meta["mime_type"] = "application/zip"
            data = _download(source_url, context)
            body = _zip_bytes_to_text(data, source_url, context, include_xlsx)
            if not body:
                body = "(ZIP 내부에서 처리 가능한 파일을 찾지 못했습니다.)"

        # ───────── 분기 6: 그 외 확장자 ─────────
        else:
            # 모르는 포맷은 처리 시도조차 하지 않고 안내문만 남기고 early return
            body = "(지원하지 않는 확장자, 건너뜀)"
            meta["extracted_text"] = body
            return f"{label}\n{body}", meta

    except Exception as e:
        # 모듈 docstring의 약속: 예외를 던지지 않고 "(처리 실패: ...)" 문자열로 회수
        body = f"(처리 실패: {e})"
        meta["extracted_text"] = body
        return f"{label}\n{body}", meta

    # 정상 분기(PDF / 엑셀 / HWPX 성공 / 이미지)의 공통 마무리:
    #   본문이 비어있어도 라벨 + 안내문은 보장해서 호출자가 항상 "라벨\n본문" 형태를 받게 한다
    text = f"{label}\n{body}" if body else f"{label}\n(추출 텍스트 없음)"
    meta["extracted_text"] = body
    return text, meta


def extract_attachment_text(path: str | Path) -> str:
    """파일 경로 기반 generic attachment text extractor.

    curriculum/document crawler 등에서 공통 사용.
    """
    file_path = Path(path)
    ext = file_path.suffix.lower()
    data = file_path.read_bytes()

    if ext == ".pdf":
        return _pdf_bytes_full(data)

    if ext == ".hwpx":
        return hwpx_bytes_to_text(data)

    if ext == ".hwp":
        return hwp_bytes_to_text(data, file_path.name)

    if ext == ".xlsx":
        return xlsx_to_text(data)

    if ext == ".xls":
        return xls_to_text(data)

    if ext in _IMAGE_EXTS:
        mime = "image/png" if ext == ".png" else "image/jpeg"
        return _image_to_text(data, mime).strip()

    raise ValueError(f"지원하지 않는 attachment 확장자: {ext}")

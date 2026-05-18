"""공주대 공지 첨부파일/본문 이미지 → 텍스트 변환 어댑터.

지원 포맷: PDF, XLSX, HWPX, HWP, 이미지(jpg/jpeg/png/gif), 본문 inline 이미지.
각 어댑터는 실패 시 빈 문자열 또는 '(처리 실패: ...)' 문자열을 돌려준다 —
호출자는 결과를 본문에 그대로 이어 붙이면 된다.
"""

# --- 표준 라이브러리 ---
import io                                          # bytes → BytesIO (zipfile/openpyxl)
import logging
import time
import zipfile                                     # HWPX = ZIP 컨테이너
from concurrent.futures import ThreadPoolExecutor  # PDF 페이지 병렬 VLM 처리
from dataclasses import asdict, dataclass
from pathlib import Path                           # 파일 확장자 추출
from xml.etree import ElementTree as ET            # HWPX 내부 XML 파싱

# --- 외부 라이브러리 ---
import openpyxl                                    # XLSX 시트 파싱

from parsers._vlm import image_to_text             # 공용 VLM 호출 유틸

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────────────────

# HWPX 본문(paragraph) XML 네임스페이스. <hp:t> 텍스트 노드 식별용.
_HWPX_PARAGRAPH_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"

# XLSX 첨부는 노이즈가 많아 기본은 임베딩 제외. 제목/본문에 아래 키워드가 포함된 공지만 활성화.
XLSX_KEYWORDS = ("교양", "수강신청", "교과목", "편성", "시간표", "강의계획", "개설")

# VLM OCR 프롬프트. "설명 문장 붙이지 마라"가 핵심 — 본문에 군더더기 섞임 방지.
_VLM_PROMPT = """이 이미지는 대학 공지글의 일부다. 이미지에 적힌 모든 텍스트와 표를 한국어 마크다운(Markdown)으로 빠짐없이 추출하라.
- 행사명, 일정, 신청기한, 신청방법, 문의처 등 숫자가 포함된 정보 항목은 절대 지어내지 말고 누락 없이 그대로 옮긴다.
- 표(Table)는 반드시 마크다운 표 문법(| | |)을 사용하여 구조를 유지한다.
- 장식/광고 문구도 모두 포함한다.
- 불필요한 부연 설명 없이 추출된 텍스트와 표만 출력한다."""


# ──────────────────────────────────────────────────────────────────────────
# 메타 자료구조
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class AssetMeta:
    """attachment_to_text가 돌려주는 메타 정보. 내부 보관 타입.

    호출자에게는 asdict()로 dict 변환해서 넘긴다 — boundary는 dict 유지.
    """
    kind: str = "attachment_other"
    filename: str = ""
    source_url: str = ""
    mime_type: str | None = None
    raw_bytes: bytes | None = None       # attachment_image에서만 채워짐
    extracted_text: str = ""


# ──────────────────────────────────────────────────────────────────────────
# 다운로드 / 공통 헬퍼
# ──────────────────────────────────────────────────────────────────────────

def _download(url: str, context) -> bytes:
    """playwright context의 request로 가져온다 (같은 TLS·쿠키·UA).

    requests를 안 쓰는 이유: 학교 공지 시스템 중 일부가 브라우저 세션
    (쿠키/UA/Referer)을 검사한다. context.request는 별도 로그인 없이 통과.
    일시 5xx/타임아웃 흡수용으로 1·2·4초 backoff 재시도.
    """
    last_exception: Exception | None = None
    for attempt in range(3):
        try:
            http_response = context.request.get(url, timeout=60000)
            if not http_response.ok:
                raise RuntimeError(f"HTTP {http_response.status} for {url}")
            return http_response.body()
        except Exception as exc:
            last_exception = exc
            if attempt < 2:
                logger.warning("download 재시도 %d/2 [%s]: %s", attempt + 1, url, exc)
                time.sleep(2 ** attempt)
    # 호출자(라우터)의 try/except에서 잡혀 "(처리 실패: ...)"로 변환
    assert last_exception is not None
    raise last_exception


def _detect_image_mime_from_magic(data: bytes) -> str | None:
    """magic number로 OpenAI Vision이 받는 4개 포맷만 식별. 그 외는 None.

    URL에 확장자가 없는 동적 endpoint(예: 메일 cidimageviewer)도 헤더로 판정 가능.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


# ──────────────────────────────────────────────────────────────────────────
# HWPX / HWP
# ──────────────────────────────────────────────────────────────────────────

def hwpx_bytes_to_text(data: bytes) -> str:
    """hwpx 패키지(ZIP)의 Contents/section*.xml에서 <hp:t> 텍스트 노드를 모두 추출.

    표/일정/문의처까지 텍스트로 들어있다. 이미지는 누락되지만 RAG 입력에는 충분.
    """
    text_runs: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zip_archive:
        # Contents/section0.xml, section1.xml, ... 순서대로 읽음
        section_xml_names = sorted(
            name for name in zip_archive.namelist()
            if name.startswith("Contents/section") and name.endswith(".xml")
        )
        for name in section_xml_names:
            root = ET.fromstring(zip_archive.read(name))
            # <hp:t> = HWPX "text run" 노드 (실제 글자가 담긴 leaf)
            for text_node in root.iter(f"{_HWPX_PARAGRAPH_NS}t"):
                if text_node.text:
                    text_runs.append(text_node.text)
    return "\n".join(text_runs).strip()


def hwpx_via_preview(preview_url: str, context) -> str:
    """공주대 synapView.do 미리보기 페이지를 playwright로 열어 텍스트 추출.

    한글 미리보기는 iframe에 본문을 렌더하므로 메인 + 모든 frame의 텍스트를 모은다.
    """
    page = context.new_page()
    try:
        # networkidle 후에도 2초 추가 대기 — synapView 렌더 완료 보장
        page.goto(preview_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(2000)

        frame_texts: list[str] = []

        # 1) 메인 frame body
        try:
            frame_texts.append(page.inner_text("body"))
        except Exception as exc:
            logger.warning("synapView main body 추출 실패 [%s]: %s", preview_url, exc)

        # 2) 모든 iframe 순회
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                frame_text = frame.inner_text("body")
                if frame_text.strip():
                    frame_texts.append(frame_text)
            except Exception as exc:
                logger.warning("synapView iframe 추출 실패 [%s, frame=%s]: %s",
                               preview_url, getattr(frame, "url", "?"), exc)
                continue

        return "\n".join(frame_texts).strip()
    finally:
        page.close()


# ──────────────────────────────────────────────────────────────────────────
# PDF
# ──────────────────────────────────────────────────────────────────────────

def _pdf_to_text_via_vlm(data: bytes) -> str:
    """모든 PDF를 고해상도 이미지로 변환한 뒤 VLM(GPT-4o-mini 등)으로 병렬 추출.
    표 레이아웃 보존 및 포스터 이미지 내 텍스트 누락 방지를 위한 통일 파이프라인.
    """
    from pdf2image import convert_from_bytes

    # 300 DPI: 품질과 메모리/속도의 최적 타협점
    page_images = convert_from_bytes(data, dpi=300)

    def _process_page(page_tuple) -> str:
        page_num, page_image = page_tuple
        # PIL 이미지 → PNG bytes → VLM
        png_buffer = io.BytesIO()
        page_image.save(png_buffer, format="PNG")
        try:
            page_text = image_to_text(png_buffer.getvalue(), "image/png", _VLM_PROMPT).strip()
            return f"--- [Page {page_num}] ---\n{page_text}"
        except Exception as exc:
            logger.warning("PDF 페이지 %d VLM 실패: %s", page_num, exc, exc_info=True)
            return f"--- [Page {page_num}] ---\n(VLM 처리 실패: {exc})"

    page_ocr_texts: list[str] = []
    # ThreadPool을 활용한 병렬 처리 (API 지연 시간 극복, rate limit 고려 max_workers=5)
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = executor.map(_process_page, enumerate(page_images, start=1))
        for res in futures:
            page_ocr_texts.append(res)

    return "\n\n".join(page_ocr_texts).strip()


# ──────────────────────────────────────────────────────────────────────────
# XLSX
# ──────────────────────────────────────────────────────────────────────────

def xlsx_relevant(*texts: str) -> bool:
    """제목·본문 등을 합쳐 XLSX_KEYWORDS 중 하나라도 포함하면 True."""
    combined_text = "\n".join(text for text in texts if text)
    return any(keyword in combined_text for keyword in XLSX_KEYWORDS)


def _detect_header_row_index(rows: list[list[str]]) -> int | None:
    """헤더 행 인덱스를 추정. 못 찾으면 None.

    휴리스틱: 첫 15행 중 비어있지 않은 셀이 5개 이상이고, 그 중 80% 이상이
    길이 40자 이하의 짧은 텍스트인 행 — 가장 셀 수가 많은 것을 선택. 그 다음 행도
    충분히 채워져 있어야 데이터 행으로 인정 (헤더 뒤에 데이터가 따라와야 헤더).
    """
    best_header_row_index: int | None = None
    best_header_score = 0
    for row_index, row in enumerate(rows[:15]):
        non_empty_cells = [cell for cell in row if cell]
        if len(non_empty_cells) < 5:
            continue
        short_cells = [cell for cell in non_empty_cells if len(cell) <= 40]
        if len(short_cells) < len(non_empty_cells) * 0.8:
            continue
        # 다음 행이 비어있으면 데이터 행 부재 → 헤더 아님
        if row_index + 1 >= len(rows):
            continue
        next_row_filled_count = sum(1 for cell in rows[row_index + 1] if cell)
        if next_row_filled_count < len(non_empty_cells) * 0.5:
            continue
        score = len(non_empty_cells)
        if score > best_header_score:
            best_header_score = score
            best_header_row_index = row_index
    return best_header_row_index


def _xlsx_to_text(data: bytes) -> str:
    """XLSX 시트를 LLM 친화적 형식으로 직렬화 (full-prefix).

    각 데이터 행을 `헤더1=값1 | 헤더2=값2 | ...` 로 변환. 한 행만 봐도 컬럼 의미가
    명확하다. 헤더가 행마다 반복돼 토큰 비용은 ~2배지만, LLM이 컬럼 의미 혼동 없이
    라벨 매칭만 하면 되어 추출 정확도 우월.

    헤더 탐지 실패 시 탭 구분 fallback.
    """
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    output_lines: list[str] = []

    for sheet in workbook.worksheets:
        output_lines.append(f"[Sheet: {sheet.title}]")

        # 1) 비어있지 않은 행만 모음. 개행/공백은 단일 공백으로 정규화 (헤더 줄바꿈 제거).
        #    '~'는 범위 구분자(2011~2016)인데 markdown 일부가 strikethrough로 해석 → '-'로 정규화.
        normalized_rows: list[list[str]] = []
        for raw_row in sheet.iter_rows(values_only=True):
            normalized_cells = [
                "" if cell_value is None else " ".join(str(cell_value).split()).replace("~", "-")
                for cell_value in raw_row
            ]
            if any(normalized_cells):
                normalized_rows.append(normalized_cells)
        if not normalized_rows:
            continue

        header_row_index = _detect_header_row_index(normalized_rows)
        if header_row_index is None:
            # 헤더 탐지 실패 — 탭 fallback
            for data_row in normalized_rows:
                output_lines.append("\t".join(data_row))
            continue

        # 2) 헤더 위쪽 행에 머지된 super-header가 있으면 prefix로 결합 (forward-fill)
        headers = list(normalized_rows[header_row_index])
        for super_header_row_index in range(header_row_index - 1, -1, -1):
            super_header_row = normalized_rows[super_header_row_index]
            non_empty_count = sum(1 for cell in super_header_row if cell)
            if non_empty_count <= 1:
                break    # 셀이 1개뿐(타이틀)이거나 모두 비면 중단
            # 머지셀은 가장 왼쪽 셀에만 값이 있음 → forward-fill로 빈 셀 채움
            forward_filled_super_headers: list[str] = []
            last_seen_value = ""
            for cell in super_header_row:
                if cell:
                    last_seen_value = cell
                forward_filled_super_headers.append(last_seen_value)
            for column_index, cell in enumerate(forward_filled_super_headers):
                if cell and column_index < len(headers) and headers[column_index]:
                    headers[column_index] = f"{cell}/{headers[column_index]}"

        # 3) [Headers] 라인: 컬럼명 1회 명시
        output_lines.append("[Headers] " + " | ".join(header for header in headers if header))

        # 4) 데이터 행: 행마다 `헤더=값` 형식
        for data_row in normalized_rows[header_row_index + 1:]:
            parts: list[str] = []
            for column_index, cell in enumerate(data_row):
                if not cell:
                    continue
                header = (
                    headers[column_index]
                    if column_index < len(headers) and headers[column_index]
                    else f"col{column_index + 1}"
                )
                parts.append(f"{header}={cell}")
            if parts:
                output_lines.append(" | ".join(parts))

    return "\n".join(output_lines).strip()


# ──────────────────────────────────────────────────────────────────────────
# inline 이미지
# ──────────────────────────────────────────────────────────────────────────

def inline_image_to_text(image_url: str, context):
    """본문 inline 이미지를 VLM으로 텍스트화.

    반환: (text, raw_bytes, mime)
      - 다운로드 실패: ("", None, None)
      - 미지원 포맷: ("", raw_bytes, None)  — bytes는 보존, VLM 호출 skip
      - 다운로드 성공/VLM 실패: ("", raw_bytes, mime) — bytes는 보존
    """
    # 1) 다운로드. 실패하면 빈 결과.
    try:
        image_bytes = _download(image_url, context)
    except Exception as exc:
        logger.warning("inline image 다운로드 실패 [%s]: %s", image_url, exc)
        return "", None, None

    # 2) 포맷 판정. 지원 4개 포맷 아니면 VLM skip (OpenAI 400 회피).
    mime = _detect_image_mime_from_magic(image_bytes)
    if mime is None:
        logger.warning("inline image 미지원 포맷, VLM skip [%s]", image_url)
        return "", image_bytes, None

    # 3) VLM 호출. 실패해도 raw_bytes는 살려둠.
    try:
        image_text = image_to_text(image_bytes, mime, _VLM_PROMPT).strip()
    except Exception as exc:
        logger.warning("inline image VLM 실패 [%s]: %s", image_url, exc, exc_info=True)
        image_text = ""

    return image_text, image_bytes, mime


# ──────────────────────────────────────────────────────────────────────────
# 첨부 → 텍스트 라우터 + 포맷별 핸들러
# ──────────────────────────────────────────────────────────────────────────

def _handle_pdf(attachment: dict, context, asset_meta: AssetMeta) -> str:
    asset_meta.kind = "attachment_pdf"
    asset_meta.mime_type = "application/pdf"
    file_bytes = _download(attachment["download_url"], context)
    return _pdf_to_text_via_vlm(file_bytes)


def _handle_xlsx(
    attachment: dict, context, asset_meta: AssetMeta,
    file_extension: str, include_xlsx: bool,
) -> str:
    asset_meta.kind = "attachment_xlsx"
    asset_meta.mime_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if file_extension == ".xlsx" else "application/vnd.ms-excel"
    )
    # 키워드 매칭 공지 + .xlsx만 본문 추출 대상. (.xls는 openpyxl 미지원이라 항상 제외.)
    if include_xlsx and file_extension == ".xlsx":
        file_bytes = _download(attachment["download_url"], context)
        return _xlsx_to_text(file_bytes)
    return f"(엑셀 첨부 — 임베딩 제외. 원본 다운로드: {attachment['download_url']})"


def _handle_hwp_family(
    attachment: dict, context, asset_meta: AssetMeta, file_extension: str,
) -> str:
    """확장자별 단일 경로:
    - .hwp  → synapView preview 전용 (공주대 게시판은 항상 preview 제공). preview_url 없거나 실패 시 빈 텍스트.
    - .hwpx → hwpx_bytes_to_text 직접 호출 (ZIP+XML 파싱이 preview보다 안정적).
    """
    asset_meta.kind = "attachment_hwpx"
    asset_meta.mime_type = (
        "application/vnd.hancom.hwpx" if file_extension == ".hwpx"
        else "application/x-hwp"
    )
    if file_extension == ".hwp":
        if not attachment.get("preview_url"):
            return ""
        return hwpx_via_preview(attachment["preview_url"], context)
    # .hwpx
    file_bytes = _download(attachment["download_url"], context)
    return hwpx_bytes_to_text(file_bytes)


def _handle_image_attachment(
    attachment: dict, context, asset_meta: AssetMeta, file_extension: str,
) -> str:
    asset_meta.kind = "attachment_image"
    asset_meta.mime_type = "image/png" if file_extension == ".png" else "image/jpeg"
    image_bytes = _download(attachment["download_url"], context)
    asset_meta.raw_bytes = image_bytes      # 멀티모달 임베딩/재처리용 원본 보존
    return image_to_text(image_bytes, asset_meta.mime_type, _VLM_PROMPT).strip()


def attachment_to_text(attachment: dict, context, include_xlsx: bool = False):
    """첨부 1건을 텍스트로 변환.

    attachment = {'filename', 'download_url', 'preview_url' | None}
    include_xlsx: 기본 False. True면 .xlsx 본문도 추출해 임베딩 대상에 포함.
                  호출자(crawler)가 xlsx_relevant(title, body)로 판정해 전달.

    반환: (text, asset_meta_dict)
      text: '[첨부: <파일명>]\\n<본문>' (실패 시 본문 자리에 사유)
      asset_meta_dict: AssetMeta를 asdict()로 변환한 dict.
        keys: kind, filename, source_url, mime_type, raw_bytes, extracted_text.
        kind = inline_image | attachment_image | attachment_pdf
             | attachment_hwpx | attachment_xlsx | attachment_other.
    """
    filename = attachment["filename"]
    file_extension = Path(filename.lower()).suffix         # .pdf / .hwpx / .jpg ...
    attachment_label = f"[첨부: {filename}]"               # RAG 컨텍스트 출처 식별용

    asset_meta = AssetMeta(
        filename=filename,
        source_url=attachment["download_url"],
    )

    # 어떤 분기에서 예외가 나더라도 "(처리 실패: ...)" 문자열로 환원 — docstring 약속.
    try:
        if file_extension == ".pdf":
            extracted_body = _handle_pdf(attachment, context, asset_meta)

        elif file_extension in (".xlsx", ".xls"):
            extracted_body = _handle_xlsx(
                attachment, context, asset_meta, file_extension, include_xlsx,
            )

        elif file_extension in (".hwpx", ".hwp"):
            extracted_body = _handle_hwp_family(
                attachment, context, asset_meta, file_extension,
            )

        elif file_extension in (".jpg", ".jpeg", ".png", ".gif"):
            extracted_body = _handle_image_attachment(
                attachment, context, asset_meta, file_extension,
            )

        else:
            # 알 수 없는 확장자: 안내문만 남기고 early return
            extracted_body = "(지원하지 않는 확장자, 건너뜀)"
            asset_meta.extracted_text = extracted_body
            return f"{attachment_label}\n{extracted_body}", asdict(asset_meta)

    except Exception as exc:
        extracted_body = f"(처리 실패: {exc})"
        asset_meta.extracted_text = extracted_body
        return f"{attachment_label}\n{extracted_body}", asdict(asset_meta)

    # 정상 분기 공통 마무리: body가 비어도 라벨 + 안내문은 보장
    text = (
        f"{attachment_label}\n{extracted_body}"
        if extracted_body else f"{attachment_label}\n(추출 텍스트 없음)"
    )
    asset_meta.extracted_text = extracted_body
    return text, asdict(asset_meta)

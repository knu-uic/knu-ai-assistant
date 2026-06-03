from dataclasses import dataclass
from typing import Callable, List, Optional

import requests
from bs4 import BeautifulSoup


from urllib3.util import create_urllib3_context


class CustomSSLContextAdapter(requests.adapters.HTTPAdapter):
    """구버전 TLS/SSL(SECLEVEL=1)을 허용하도록 urllib3의 SSLContext를 커스텀하는 어댑터."""
    def init_poolmanager(self, *args, **kwargs):
        context = create_urllib3_context()
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs['ssl_context'] = context
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        context = create_urllib3_context()
        context.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs['ssl_context'] = context
        return super().proxy_manager_for(*args, **kwargs)


@dataclass(frozen=True)
class StaticPageConfig:
    source_code: str
    source_name: str
    department: str | None
    kind: str
    base_url: str
    page_url: str
    wait_selector: str
    title_selector: str
    content_selector: str


class StaticPageCrawler:
    def __init__(self, config: StaticPageConfig):
        self.config = config
        self.SOURCE_CODE = config.source_code
        self.SOURCE_NAME = config.source_name
        self.DEPARTMENT = config.department
        self.KIND = config.kind
        self.BASE_URL = config.base_url

        self.session = requests.Session()
        self.session.mount("https://", CustomSSLContextAdapter())
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            )
        })

    def crawling(self, should_skip: Optional[Callable[[str], bool]] = None) -> List[dict]:
        print(f"\n=== {self.SOURCE_NAME} 수집: {self.config.page_url} ===")

        response = self.session.get(self.config.page_url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        try:
            title_el = soup.select_one(self.config.title_selector)
            title = title_el.get_text(" ", strip=True) if title_el else self.SOURCE_NAME
        except Exception:
            title = self.SOURCE_NAME

        try:
            content_el = soup.select_one(self.config.content_selector)
            content = content_el.get_text("\n", strip=True) if content_el else ""
        except Exception:
            content = ""

        # static page는 대부분 body 중심 문서
        body_content = content
        attachment_names: list[str] = []
        attachment_contents: list[dict] = []

        if not content:
            print(f"[{self.SOURCE_CODE}] 본문 추출 실패")
            return []

        print(f"제목: {title}")
        print(content[:300] + ("..." if len(content) > 300 else ""))

        return [{
            "title": title,
            "date": "",
            "content": content,

            # 신규 구조
            "body_content": body_content,
            "attachment_names": attachment_names,
            "attachment_contents": attachment_contents,

            "url": self.config.page_url,
            "assets": [],
            "replace_by_source": True,
        }]

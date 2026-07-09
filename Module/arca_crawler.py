"""아카라이브(Arcalive) 전용 크롤러.

DCInsideImageCrawler의 Module/crawler.py와 동일한 인터페이스를 제공하지만:
- cloudscraper로 요청 (맥 IP 경유 시 Cloudflare 챌린지 미발생)
- 게시글 내 모든 이미지를 추출 (DCInside는 최상단 1개만)
- 아카라이브 전용 HTML 셀렉터 사용
"""
from __future__ import annotations
import logging
import os
import re
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup, SoupStrainer

from Module.lru_cache import LRUCache

logger = logging.getLogger(__name__)

ARCA_BASE = "https://arca.live"
IMAGE_CDN_RE = re.compile(r"//ac[-a-z0-9]*\.namu\.la/")
_VROW_STRAINER = SoupStrainer(attrs={"class": re.compile(r"\bvrow\b")})
POST_SKIP_COUNT = 10

# SOCKS 프록시 설정 (OCI → 맥 터널)
_ARCA_SOCKS_PROXY = os.getenv("ARCA_SOCKS_PROXY", "")


def _mask_proxy(url: str) -> str:
    """프록시 URL의 자격증명(user:pass@)을 로그에 노출하지 않도록 가린다."""
    return re.sub(r"//[^/@]+@", "//***:***@", url)


def _create_session() -> object:
    """cloudscraper 세션 생성. ARCA_SOCKS_PROXY가 설정돼 있으면 SOCKS 경유."""
    s = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True, "mobile": False},
    )
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    })
    if _ARCA_SOCKS_PROXY:
        s.proxies.update({"http": _ARCA_SOCKS_PROXY, "https": _ARCA_SOCKS_PROXY})
        logger.info(f"아카라이브 SOCKS 프록시 사용: {_mask_proxy(_ARCA_SOCKS_PROXY)}")
    return s


class ArcaliveCrawler:
    """아카라이브 게시글 크롤러."""

    def __init__(self, base_url: object, session: object=None) -> None:
        self.base_url = base_url
        self.sent_items = LRUCache()
        self.session = session or _create_session()

    # ---------- 포스트 목록 파싱 ----------

    def get_latest_posts(self, max_posts: object=5) -> object:
        try:
            res = self.session.get(self.base_url, timeout=15)
            res.raise_for_status()
        except Exception as e:
            logger.warning(f"아카라이브 목록 요청 실패: {e}")
            return []

        soup = BeautifulSoup(res.text, "lxml", parse_only=_VROW_STRAINER)
        posts = []

        for vrow in soup.select("div.vrow.hybrid"):
            post = self._parse_hybrid_row(vrow)
            if post:
                posts.append(post)

        if not posts:
            for vrow in soup.select("a.vrow.column"):
                post = self._parse_column_row(vrow)
                if post:
                    posts.append(post)

        posts = posts[POST_SKIP_COUNT:]
        new_posts = []
        for post in posts:
            dedup_key = (post["title"], post["post_id"])
            if dedup_key not in self.sent_items:
                new_posts.append(post)

        for post in new_posts[:max_posts]:
            self.sent_items.add((post["title"], post["post_id"]))

        return new_posts[:max_posts]

    def _parse_hybrid_row(self, vrow: object) -> object:
        title_el = vrow.select_one("a.title.hybrid-title")
        if not title_el:
            return None
        href = title_el.get("href", "")
        if not href:
            return None
        if vrow.select_one(".media-icon") is None:
            return None
        return {
            "link": urljoin(ARCA_BASE, href),
            "title": title_el.get_text(strip=True),
            "post_id": self._extract_post_id(href),
        }

    def _parse_column_row(self, vrow: object) -> object:
        href = vrow.get("href", "")
        if not href:
            return None
        title_el = vrow.select_one("span.title")
        if not title_el:
            return None
        if vrow.select_one(".media-icon") is None:
            return None
        return {
            "link": urljoin(ARCA_BASE, href),
            "title": title_el.get_text(strip=True),
            "post_id": self._extract_post_id(href),
        }

    @staticmethod
    def _extract_post_id(href: str) -> str:
        m = re.search(r"/b/[^/]+/(\d+)", href)
        return m.group(1) if m else ""

    # ---------- 개별 게시글 이미지 추출 ----------

    def extract_all_images(self, post_url: str) -> list[dict[str, str]]:
        try:
            res = self.session.get(post_url, timeout=15)
            res.raise_for_status()
        except Exception as e:
            logger.warning(f"아카라이브 게시글 요청 실패 ({post_url}): {e}")
            return []

        soup = BeautifulSoup(res.text, "lxml")
        images = []
        seen_urls = set()

        body = soup.select_one("div.article-body")
        if body:
            for img in body.find_all("img"):
                self._collect_image(img, images, seen_urls, post_url)

        content = soup.select_one(".fr-view.article-content")
        if content and content.parent != body:
            for img in content.find_all("img"):
                self._collect_image(img, images, seen_urls, post_url)

        logger.info(f"아카라이브 게시글 이미지 {len(images)}개 발견: {post_url}")
        return images

    def _collect_image(
        self,
        img_tag: object,
        images: list[dict[str, str]],
        seen_urls: set[str],
        post_url: str = "",
    ) -> None:
        classes = img_tag.get("class", [])
        if "arca-emoticon" in classes or img_tag.get("data-type") == "emoticon":
            return

        src = img_tag.get("src", "")
        orig = img_tag.get("data-originalurl", "")
        if not IMAGE_CDN_RE.search(src) and not IMAGE_CDN_RE.search(orig):
            return

        download_url = orig or src
        if not download_url.startswith("http"):
            download_url = "https:" + download_url

        clean_url = download_url.split("?")[0]
        if clean_url in seen_urls:
            return
        seen_urls.add(clean_url)

        filename = clean_url.split("/")[-1]
        if not filename:
            pid = self._extract_post_id(post_url) if post_url else ""
            filename = f"arca_{pid}_{len(images)}.jpg"

        images.append({
            "url": download_url,
            "original_url": orig or src,
            "filename": filename,
        })

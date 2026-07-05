"""
아카라이브(Arcalive) 전용 크롤러.

DCInsideImageCrawler의 Module/crawler.py와 동일한 인터페이스를 제공하지만:
- Cloudflare 우회를 위해 cloudscraper 사용
- 게시글 내 모든 이미지를 추출 (DCInside는 최상단 1개만)
- 아카라이브 전용 HTML 셀렉터 사용
"""
import logging
import re
from collections import OrderedDict
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup, SoupStrainer

logger = logging.getLogger(__name__)

# 아카라이브 base domain
ARCA_BASE = "https://arca.live"

# 이미지 CDN 도메인 (namu.la)
IMAGE_CDN_RE = re.compile(r"//ac-[-a-z]+\d*\.namu\.la/")

MAX_CACHE_SIZE = 500

# 포스트 목록 파싱용 Strainer — vrow 요소만 수집
_VROW_STRAINER = SoupStrainer(attrs={"class": re.compile(r"\bvrow\b")})


class ArcaliveCrawler:
    """아카라이브 게시글 크롤러.
    
    DCInsideCrawler와 유사하나:
    - get_latest_post() 대신 get_latest_posts() — 여러 새 글 반환
    - extract_all_images(url) — 게시글 내 모든 이미지 반환
    """

    def __init__(self, base_url):
        self.base_url = base_url
        # 중복 방지: (title, post_id) 쌍을 BoundedSet으로 관리
        self.sent_items = BoundedSet()
        self.scraper = cloudscraper.create_scraper()

    # ---------- 포스트 목록 파싱 ----------

    def get_latest_posts(self, max_posts=5):
        """최신 게시글 중 이미지가 있는 새 글들을 반환한다.
        
        아카라이브는 두 가지 레이아웃이 있음:
        - hybrid: 핫딜/거래 게시판 (a.title.hybrid-title)
        - column: 일반 이미지 게시판 (a.vrow.column > span.title)
        
        Returns:
            list[dict] — 각 항목: {'link': str, 'title': str, 'post_id': str}
        """
        try:
            res = self.scraper.get(self.base_url, timeout=15)
            res.raise_for_status()
        except Exception as e:
            logger.warning(f"아카라이브 목록 요청 실패: {e}")
            return []

        soup = BeautifulSoup(res.text, "lxml", parse_only=_VROW_STRAINER)

        posts = []

        # === 1) hybrid 레이아웃 (핫딜 등) ===
        for vrow in soup.select("div.vrow.hybrid"):
            post = self._parse_hybrid_row(vrow)
            if post:
                posts.append(post)

        # === 2) column 레이아웃 (일반 이미지 게시판) ===
        if not posts:
            for vrow in soup.select("a.vrow.column"):
                post = self._parse_column_row(vrow)
                if post:
                    posts.append(post)

        # 중복 제거 + 이미 전송한 글 필터링
        new_posts = []
        for post in posts:
            dedup_key = (post["title"], post["post_id"])
            if dedup_key not in self.sent_items:
                self.sent_items.add(dedup_key)
                new_posts.append(post)

        return new_posts[:max_posts]

    def _parse_hybrid_row(self, vrow):
        """hybrid 레이아웃(vrow.hybrid)에서 게시글 정보 추출."""
        title_el = vrow.select_one("a.title.hybrid-title")
        if not title_el:
            return None

        href = title_el.get("href", "")
        if not href:
            return None

        title = title_el.get_text(strip=True)
        post_id = self._extract_post_id(href)

        # 이미지 포함 여부 확인
        has_image = vrow.select_one(".media-icon") is not None
        if not has_image:
            return None

        return {
            "link": urljoin(ARCA_BASE, href),
            "title": title,
            "post_id": post_id,
        }

    def _parse_column_row(self, vrow):
        """column 레이아웃(a.vrow.column)에서 게시글 정보 추출."""
        href = vrow.get("href", "")
        if not href:
            return None

        title_el = vrow.select_one("span.title")
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        post_id = self._extract_post_id(href)

        has_image = vrow.select_one(".media-icon") is not None
        if not has_image:
            return None

        return {
            "link": urljoin(ARCA_BASE, href),
            "title": title,
            "post_id": post_id,
        }

    @staticmethod
    def _extract_post_id(href: str) -> str:
        """/b/{board_id}/{post_id} 형식에서 post_id 추출."""
        m = re.search(r"/b/[^/]+/(\d+)", href)
        return m.group(1) if m else ""

    # ---------- 개별 게시글 이미지 추출 ----------

    def extract_all_images(self, post_url: str) -> list[dict]:
        """게시글 내 모든 이미지의 URL을 추출한다.
        
        아카라이브는 두 가지 이미지 위치를 가짐:
        1. div.article-body #defaultImage img — 썸네일/대표 이미지 (media-icon 트리거)
        2. div.fr-view.article-content img — 본문 인라인 이미지
        
        Returns:
            list[dict]: [{'url': str, 'original_url': str, 'filename': str}, ...]
            빈 리스트면 이미지 없음.
        """
        try:
            res = self.scraper.get(post_url, timeout=15)
            res.raise_for_status()
        except Exception as e:
            logger.warning(f"아카라이브 게시글 요청 실패 ({post_url}): {e}")
            return []

        soup = BeautifulSoup(res.text, "lxml")
        images = []
        seen_urls = set()

        # 1) article-body 내 모든 이미지 수집
        body = soup.select_one("div.article-body")
        if body:
            for img in body.find_all("img"):
                self._collect_image(img, images, seen_urls)

        # 2) fr-view 내 이미지 (article-body 밖에 있을 경우 대비)
        content = soup.select_one(".fr-view.article-content")
        if content and content.parent != body:
            for img in content.find_all("img"):
                self._collect_image(img, images, seen_urls)

        logger.info(f"아카라이브 게시글 이미지 {len(images)}개 발견: {post_url}")
        return images

    def _collect_image(self, img_tag, images: list, seen_urls: set, post_url: str = ""):
        """단일 img 태그에서 이미지 URL을 수집한다."""
        src = img_tag.get("src", "")
        orig = img_tag.get("data-originalurl", "")

        # namu.la CDN 이미지만 수집
        if not IMAGE_CDN_RE.search(src) and not IMAGE_CDN_RE.search(orig):
            return

        # 원본 URL 우선, 없으면 src
        download_url = orig or src
        if not download_url.startswith("http"):
            download_url = "https:" + download_url

        # 중복 제거 (쿼리스트링 제거 후 비교)
        clean_url = download_url.split("?")[0]
        if clean_url in seen_urls:
            return
        seen_urls.add(clean_url)

        # filename 추출
        filename = clean_url.split("/")[-1]
        if not filename:
            pid = self._extract_post_id(post_url) if post_url else ""
            filename = f"arca_{pid}_{len(images)}.jpg"

        images.append({
            "url": download_url,
            "original_url": orig or src,
            "filename": filename,
        })


class BoundedSet:
    """크기가 제한된 set (FIFO 방식으로 오래된 항목 제거)"""

    def __init__(self, maxsize=MAX_CACHE_SIZE):
        self._data = OrderedDict()
        self._maxsize = maxsize

    def __contains__(self, item):
        return item in self._data

    def add(self, item):
        if item in self._data:
            self._data.move_to_end(item)
            return
        if len(self._data) >= self._maxsize:
            self._data.popitem(last=False)
        self._data[item] = None

    def clear(self):
        self._data.clear()

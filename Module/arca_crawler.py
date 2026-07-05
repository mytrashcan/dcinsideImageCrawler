"""
아카라이브(Arcalive) 전용 크롤러.

DCInsideImageCrawler의 Module/crawler.py와 동일한 인터페이스를 제공하지만:
- Cloudflare 우회를 위해 nodriver (Chromium CDP) 사용
- 게시글 내 모든 이미지를 추출 (DCInside는 최상단 1개만)
- 아카라이브 전용 HTML 셀렉터 사용
"""
import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, SoupStrainer

from Module.crawler import BoundedSet

logger = logging.getLogger(__name__)

# 아카라이브 base domain
ARCA_BASE = "https://arca.live"

# 이미지 CDN 도메인 (namu.la)
IMAGE_CDN_RE = re.compile(r"//ac-[-a-z]+\d*\.namu\.la/")

# 포스트 목록 파싱용 Strainer -- vrow 요소만 수집
_VROW_STRAINER = SoupStrainer(attrs={"class": re.compile(r"\bvrow\b")})

# 최신 글 중 몇 개를 건너뛸지 -- 완장/알바 정제물을 타겟으로 함
POST_SKIP_COUNT = 10


class ArcaliveCrawler:
    """아카라이브 게시글 크롤러.

    nodriver(Chromium CDP)로 Cloudflare JS 챌린지를 우회한다.
    """

    def __init__(self, base_url):
        self.base_url = base_url
        self.sent_items = BoundedSet()
        self._browser = None
        self._tab = None
        self._started = False

    async def _ensure_browser(self):
        """nodriver 브라우저가 실행 중인지 확인하고 필요하면 시작."""
        if self._started:
            return
        import nodriver as uc

        logger.info("아카라이브 크롤러: Chromium 브라우저 시작 중...")
        self._browser = await uc.Browser.create(
            headless=True,
            no_sandbox=True,
        )
        self._tab = self._browser.main_tab
        self._started = True
        logger.info("아카라이브 크롤러: Chromium 브라우저 시작됨")

        # Cloudflare 챌린지 우회를 위한 세션 웜업
        try:
            await self._tab.get(ARCA_BASE)
            await self._tab.sleep(3)  # JS 챌린지 완료 대기
            logger.debug("아카라이브 세션 웜업 완료")
        except Exception:
            pass

    async def _get_page_html(self, url: str, timeout: int = 20) -> str:
        """nodriver로 URL을 열고 HTML을 반환."""
        await self._ensure_browser()
        try:
            await self._tab.get(url, new_tab=False)
            # 페이지 로딩 + JS 실행 대기
            await self._tab.sleep(3)
            content = await self._tab.page.content()
            return content
        except Exception as e:
            raise Exception(f"nodriver 요청 실패 ({url}): {e}")

    # ---------- 포스트 목록 파싱 ----------

    async def get_latest_posts(self, max_posts=5):
        """최신 게시글 중 이미지가 있는 새 글들을 반환한다.

        아카라이브는 두 가지 레이아웃이 있음:
        - hybrid: 핫딜/거래 게시판 (a.title.hybrid-title)
        - column: 일반 이미지 게시판 (a.vrow.column > span.title)

        Returns:
            list[dict]
        """
        try:
            html = await self._get_page_html(self.base_url)
        except Exception as e:
            logger.warning(f"아카라이브 목록 요청 실패: {e}")
            return []

        soup = BeautifulSoup(html, "lxml", parse_only=_VROW_STRAINER)

        posts = []

        # === 1) hybrid 레이아웃 ===
        for vrow in soup.select("div.vrow.hybrid"):
            post = self._parse_hybrid_row(vrow)
            if post:
                posts.append(post)

        # === 2) column 레이아웃 ===
        if not posts:
            for vrow in soup.select("a.vrow.column"):
                post = self._parse_column_row(vrow)
                if post:
                    posts.append(post)

        posts = posts[POST_SKIP_COUNT:]

        # 중복 제거
        new_posts = []
        for post in posts:
            dedup_key = (post["title"], post["post_id"])
            if dedup_key not in self.sent_items:
                new_posts.append(post)

        # 반환할 포스트만 sent_items에 기록
        for post in new_posts[:max_posts]:
            self.sent_items.add((post["title"], post["post_id"]))

        return new_posts[:max_posts]

    def _parse_hybrid_row(self, vrow):
        title_el = vrow.select_one("a.title.hybrid-title")
        if not title_el:
            return None
        href = title_el.get("href", "")
        if not href:
            return None
        title = title_el.get_text(strip=True)
        post_id = self._extract_post_id(href)
        if vrow.select_one(".media-icon") is None:
            return None
        return {
            "link": urljoin(ARCA_BASE, href),
            "title": title,
            "post_id": post_id,
        }

    def _parse_column_row(self, vrow):
        href = vrow.get("href", "")
        if not href:
            return None
        title_el = vrow.select_one("span.title")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        post_id = self._extract_post_id(href)
        if vrow.select_one(".media-icon") is None:
            return None
        return {
            "link": urljoin(ARCA_BASE, href),
            "title": title,
            "post_id": post_id,
        }

    @staticmethod
    def _extract_post_id(href: str) -> str:
        m = re.search(r"/b/[^/]+/(\d+)", href)
        return m.group(1) if m else ""

    # ---------- 개별 게시글 이미지 추출 ----------

    async def extract_all_images(self, post_url: str) -> list[dict]:
        """게시글 내 모든 이미지 URL 추출."""
        try:
            html = await self._get_page_html(post_url)
        except Exception as e:
            logger.warning(f"아카라이브 게시글 요청 실패 ({post_url}): {e}")
            return []

        soup = BeautifulSoup(html, "lxml")
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

    def _collect_image(self, img_tag, images: list, seen_urls: set, post_url: str = ""):
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

    async def close(self):
        """브라우저 종료."""
        if self._browser:
            try:
                await self._browser.stop()
                logger.info("아카라이브 크롤러: 브라우저 종료됨")
            except Exception:
                pass
            self._started = False
            self._browser = None
            self._tab = None

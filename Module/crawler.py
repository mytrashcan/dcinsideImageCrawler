from __future__ import annotations

import logging
from urllib.parse import parse_qs, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, SoupStrainer

from Module.config import BS_PARSER, HEADERS, REQUEST_TIMEOUT

# BoundedSet 은 공통 LRUCache 로 통합됨 — 기존 import(arca_crawler/테스트) 호환 위해 재노출
from Module.lru_cache import BoundedSet, LRUCache  # noqa: F401

logger = logging.getLogger(__name__)

MAX_CACHE_SIZE = 500

# 최신 일반 게시물은 갤러리 관리자/운영자가 유해 게시물을 먼저 차단할 수 있도록 보류한다.
POST_SAFETY_SKIP_COUNT = 20

# tr 요소만 파싱하여 파싱 비용 절감
# (SoupStrainer의 class_ 매칭은 다중 클래스 속성에서 동작하지 않으므로 태그로만 거름)
_POST_ROW_STRAINER = SoupStrainer("tr")


class DCInsideCrawler:
    def __init__(self, base_url: object) -> None:
        self.base_url = base_url
        self.sent_post_ids = LRUCache(MAX_CACHE_SIZE)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def image_check(self, element: object) -> object:
        """이미지 포함 여부 체크"""
        return element.select_one(".icon_pic") is not None

    def get_latest_post(self) -> object:
        """최신 게시글 정보 가져오기 (동기)"""
        try:
            res = self.session.get(self.base_url, timeout=REQUEST_TIMEOUT)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, BS_PARSER, parse_only=_POST_ROW_STRAINER)

            posts = soup.select("tr.ub-content")
            if not posts:
                return None

            normal_post_count = 0
            for post in posts:
                try:
                    if post.get("data-type") == "icon_notice":
                        continue

                    title_element = post.select_one('td.gall_tit a[href*="/board/view/"]')
                    if not title_element:
                        continue

                    link = urljoin("https://gall.dcinside.com", title_element.get("href", ""))
                    parts = urlsplit(link)
                    post_ids = parse_qs(parts.query).get("no", [])
                    if parts.hostname != "gall.dcinside.com" or not post_ids:
                        continue

                    normal_post_count += 1
                    if normal_post_count <= POST_SAFETY_SKIP_COUNT:
                        continue

                    post_id = post_ids[0]
                    title = title_element.text.strip()
                    image_insert = self.image_check(post)

                    logger.debug(f"{title} {link} {image_insert}")

                    if post_id not in self.sent_post_ids:
                        # 다음 사이클에서 같은 게시글을 재다운로드하지 않도록 기록
                        self.sent_post_ids.add(post_id)
                        return {
                            'link': link,
                            'title': title,
                            'post_id': post_id,
                            'has_image': image_insert
                        }

                except Exception as e:
                    logger.warning(f"게시글 파싱 실패: {e}")
                    continue

            return None

        except requests.Timeout:
            logger.warning(f"크롤링 타임아웃: {self.base_url}")
            return None
        except requests.RequestException as e:
            logger.error(f"크롤링 요청 실패: {e}")
            return None

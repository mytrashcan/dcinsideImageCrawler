from __future__ import annotations

import logging

import requests
from bs4 import BeautifulSoup, SoupStrainer

from Module.config import BS_PARSER, HEADERS, REQUEST_TIMEOUT

# BoundedSet 은 공통 LRUCache 로 통합됨 — 기존 import(arca_crawler/테스트) 호환 위해 재노출
from Module.lru_cache import BoundedSet, LRUCache  # noqa: F401

logger = logging.getLogger(__name__)

MAX_CACHE_SIZE = 500

# 목록 상단의 공지/이벤트/완장성 글을 건너뛰고 일반 게시글부터 본다
POST_SKIP_COUNT = 20

# tr 요소만 파싱하여 파싱 비용 절감
# (SoupStrainer의 class_ 매칭은 다중 클래스 속성에서 동작하지 않으므로 태그로만 거름)
_POST_ROW_STRAINER = SoupStrainer("tr")


class DCInsideCrawler:
    def __init__(self, base_url: object) -> None:
        self.base_url = base_url
        self.sent_titles = LRUCache(MAX_CACHE_SIZE)
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

            for post in posts[POST_SKIP_COUNT:]:
                try:
                    title_element = post.select_one("td.gall_tit > a:first-child")
                    if not title_element:
                        continue

                    link = "https://gall.dcinside.com" + title_element.get("href", "")
                    title = title_element.text.strip()
                    image_insert = self.image_check(post)

                    logger.debug(f"{title} {link} {image_insert}")

                    if title not in self.sent_titles:
                        # 다음 사이클에서 같은 게시글을 재다운로드하지 않도록 기록
                        self.sent_titles.add(title)
                        return {
                            'link': link,
                            'title': title,
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

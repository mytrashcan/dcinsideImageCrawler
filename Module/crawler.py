import logging
from collections import OrderedDict

import requests
from bs4 import BeautifulSoup, SoupStrainer

from Module.config import BS_PARSER, HEADERS, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

MAX_CACHE_SIZE = 500

# tr 요소만 파싱하여 파싱 비용 절감
# (SoupStrainer의 class_ 매칭은 다중 클래스 속성에서 동작하지 않으므로 태그로만 거름)
_POST_ROW_STRAINER = SoupStrainer("tr")


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


class DCInsideCrawler:
    def __init__(self, base_url):
        self.base_url = base_url
        self.sent_titles = BoundedSet()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def image_check(self, element):
        """이미지 포함 여부 체크"""
        return element.select_one(".icon_pic") is not None

    def get_latest_post(self):
        """최신 게시글 정보 가져오기 (동기)"""
        try:
            res = self.session.get(self.base_url, timeout=REQUEST_TIMEOUT)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, BS_PARSER, parse_only=_POST_ROW_STRAINER)

            posts = soup.select("tr.ub-content")
            if not posts:
                return None

            for post in posts[20:]:
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

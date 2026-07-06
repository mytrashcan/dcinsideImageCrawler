"""크기 제한 LRU 집합.

DCInside 크롤러의 게시글 제목 중복 방지, Arca 크롤러의 게시글 dedup,
ImageHandler의 이미지 해시 중복 방지가 모두 동일한
"OrderedDict + FIFO 축출" 패턴이라 한 곳으로 모은다.
"""
from collections import OrderedDict

DEFAULT_MAX_SIZE = 500


class LRUCache:
    """최대 크기가 제한된 집합. 가득 차면 가장 오래된 항목부터 축출(FIFO)."""

    def __init__(self, maxsize: int = DEFAULT_MAX_SIZE):
        self._data: OrderedDict = OrderedDict()
        self._maxsize = maxsize

    def __contains__(self, item) -> bool:
        return item in self._data

    def __len__(self) -> int:
        return len(self._data)

    def add(self, item) -> None:
        """항목을 추가한다(이미 있으면 최근 사용으로 갱신)."""
        self.add_if_absent(item)

    def add_if_absent(self, item) -> bool:
        """항목을 추가하고, **이미 존재했는지 여부**를 반환한다.

        중복 체크와 추가를 한 번에 수행한다. 반환값이 True면 이미 본 항목(=중복).
        """
        if item in self._data:
            self._data.move_to_end(item)
            return True
        if len(self._data) >= self._maxsize:
            self._data.popitem(last=False)
        self._data[item] = None
        return False

    def clear(self) -> None:
        self._data.clear()


# 기존 import 호환용 별칭 (Module.crawler.BoundedSet 를 참조하던 코드/테스트 유지)
BoundedSet = LRUCache

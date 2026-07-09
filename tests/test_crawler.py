from __future__ import annotations
from unittest.mock import MagicMock

import pytest

from Module.crawler import BoundedSet, DCInsideCrawler


def make_post_row(title: object, post_id: object, has_image: object=False) -> object:
    icon = '<em class="icon_img icon_pic"></em>' if has_image else ""
    return f"""
    <tr class="ub-content us-post">
        <td class="gall_tit ub-word">
            <a href="/mgallery/board/view/?id=test&no={post_id}">{title}</a>{icon}
        </td>
    </tr>
    """


def make_list_html(rows: object) -> object:
    return f"<html><body><table><tbody>{''.join(rows)}</tbody></table></body></html>"


def make_crawler(html: object) -> object:
    crawler = DCInsideCrawler("https://gall.dcinside.com/mgallery/board/lists/?id=test")
    response = MagicMock()
    response.text = html
    response.raise_for_status = MagicMock()
    crawler.session = MagicMock()
    crawler.session.get.return_value = response
    return crawler


class TestBoundedSet:
    def test_add_and_contains(self) -> None:
        s = BoundedSet(maxsize=3)
        s.add("a")
        assert "a" in s
        assert "b" not in s

    def test_evicts_oldest_when_full(self) -> None:
        s = BoundedSet(maxsize=2)
        s.add("a")
        s.add("b")
        s.add("c")
        assert "a" not in s
        assert "b" in s
        assert "c" in s

    def test_readd_moves_to_end(self) -> None:
        s = BoundedSet(maxsize=2)
        s.add("a")
        s.add("b")
        s.add("a")  # a를 최신으로 갱신
        s.add("c")  # b가 제거되어야 함
        assert "a" in s
        assert "b" not in s

    def test_clear(self) -> None:
        s = BoundedSet(maxsize=2)
        s.add("a")
        s.clear()
        assert "a" not in s


class TestGetLatestPost:
    def test_skips_first_20_rows(self) -> None:
        # 앞 20개는 건너뛰므로 21번째 행이 반환되어야 함
        rows = [make_post_row(f"post{i}", i, has_image=True) for i in range(25)]
        crawler = make_crawler(make_list_html(rows))

        post = crawler.get_latest_post()

        assert post is not None
        assert post["title"] == "post20"
        assert post["link"].endswith("no=20")
        assert post["has_image"] is True

    def test_detects_post_without_image(self) -> None:
        rows = [make_post_row(f"post{i}", i, has_image=False) for i in range(25)]
        crawler = make_crawler(make_list_html(rows))

        post = crawler.get_latest_post()

        assert post is not None
        assert post["has_image"] is False

    def test_does_not_return_same_post_twice(self) -> None:
        rows = [make_post_row(f"post{i}", i, has_image=True) for i in range(25)]
        crawler = make_crawler(make_list_html(rows))

        first = crawler.get_latest_post()
        second = crawler.get_latest_post()

        assert first["title"] == "post20"
        assert second is None or second["title"] != first["title"]

    def test_returns_none_when_no_posts(self) -> None:
        crawler = make_crawler("<html><body></body></html>")
        assert crawler.get_latest_post() is None

    def test_returns_none_on_request_error(self) -> None:
        import requests

        crawler = make_crawler("")
        crawler.session.get.side_effect = requests.ConnectionError("boom")
        assert crawler.get_latest_post() is None


@pytest.mark.parametrize("has_image", [True, False])
def test_image_check(has_image: object) -> None:
    from bs4 import BeautifulSoup

    html = make_post_row("t", 1, has_image=has_image)
    row = BeautifulSoup(html, "html.parser").select_one("tr")
    crawler = DCInsideCrawler("https://example.com")
    assert crawler.image_check(row) is has_image

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "sec-ch-ua-mobile": "?0",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
    "Sec-Fetch-Dest": "document",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "ko-KR,ko;q=0.9"
}

class DCInsideCrawler:
    def __init__(self, base_url):
        self.base_url = base_url
        self.sent_titles = set()
        self.sent_image_links = set()

    def image_check(self, element):
        """이미지 포함 여부 체크"""
        return "icon_pic" in str(element)

    def finder(self):
        """크롤링 시작지점 위치 찾기"""
        try:
            res = requests.get(self.base_url, headers=HEADERS)
            res.raise_for_status()  # 상태 코드 확인
            soup = BeautifulSoup(res.text, 'html.parser')

            if "mgallery" in self.base_url or "mini" in self.base_url:
                pointer = soup.select("td.gall_subject")
            else:
                pointer = soup.select("td.gall_num")

            startpoint = 0
            for item in pointer:
                if any(x in item.text for x in ["공지", "설문", "이슈", "고정"]):
                    startpoint += 1

            return startpoint

        except Exception as e:
            return None

    async def get_latest_post(self):
        """최신 게시글 정보 가져오기"""
        try:
            res = requests.get(self.base_url, headers=HEADERS)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')

            startpoint = self.finder()
            posts = soup.select("tr.ub-content")
            
            if not posts:
                return None

            for post in posts[startpoint:]:
                try:
                    title_element = post.select_one("td.gall_tit > a:first-child")
                    if not title_element:
                        continue

                    link = "https://gall.dcinside.com" + title_element.get("href", "")
                    title = title_element.text.strip()
                    image_insert = self.image_check(post)

                    print(f"{title} {link} {image_insert}")

                    if title not in self.sent_titles:
                        return {
                            'link': link,
                            'title': title,
                            'has_image': image_insert
                        }

                except Exception as e:
                    continue

            return None

        except Exception as e:
            return None
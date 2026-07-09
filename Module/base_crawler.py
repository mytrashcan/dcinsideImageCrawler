from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Post:
    link: str
    title: str
    post_id: str
    has_image: bool

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "link": self.link,
            "title": self.title,
            "post_id": self.post_id,
            "has_image": self.has_image,
        }


class BaseCrawler(ABC):
    @abstractmethod
    def get_new_posts(self, max_posts: int = 5) -> list[Post]:
        raise NotImplementedError

import re
from typing import ClassVar
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from homework_reviewer.models.submission import LinkInfo


class LinkParser:
    _url_pattern: ClassVar[re.Pattern[str]] = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
    _google_sheet_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"^https?://docs\.google\.com/spreadsheets/d/([^/?#]+)", re.IGNORECASE
    )
    _headers: ClassVar[dict[str, str]] = {"User-Agent": "HomeworkReviewer/1.0 (+https://localhost)"}

    def extract_urls(self, text: str) -> list[str]:
        urls: list[str] = []
        for match in self._url_pattern.findall(text):
            url = match.rstrip(".,;:!?)]}>'\"")
            if url and url not in urls:
                urls.append(url)
        return urls

    def resolve_link(self, url: str) -> LinkInfo:
        is_google_doc = "docs.google.com" in url.lower()
        request_url = self._google_sheet_export_url(url) or url
        try:
            response = requests.get(request_url, headers=self._headers, timeout=10, allow_redirects=True)
        except requests.Timeout:
            return LinkInfo(
                url=url, status_code=0, is_accessible=False,
                content_summary="Превышено время ожидания ответа.", is_google_doc=is_google_doc,
            )
        except requests.RequestException as error:
            return LinkInfo(
                url=url, status_code=0, is_accessible=False,
                content_summary=f"Ошибка запроса: {error}", is_google_doc=is_google_doc,
            )
        if response.status_code != 200:
            default_summary = f"Ресурс вернул HTTP {response.status_code}."
            summary = {403: "Доступ запрещён (HTTP 403).", 404: "Ресурс не найден (HTTP 404)."}
            summary = summary.get(response.status_code, default_summary)
            return LinkInfo(
                url=url, status_code=response.status_code, is_accessible=False,
                content_summary=summary, is_google_doc=is_google_doc,
            )
        if self._google_sheet_export_url(url):
            text = response.text.strip()
        else:
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            body = soup.get_text(" ", strip=True)
            text = " ".join(part for part in (title, body) if part)
        return LinkInfo(
            url=url, status_code=response.status_code, is_accessible=True,
            content_summary=text[:2000], is_google_doc=is_google_doc,
        )

    def _google_sheet_export_url(self, url: str) -> str | None:
        match = self._google_sheet_pattern.match(url)
        if not match:
            return None
        return f"https://docs.google.com/spreadsheets/d/{quote(match.group(1), safe='')}/export?format=csv"

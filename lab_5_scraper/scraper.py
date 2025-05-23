"""
Crawler implementation.
"""

# pylint: disable=too-many-arguments, too-many-instance-attributes, unused-import, undefined-variable, unused-argument
import datetime
import json
import pathlib
import re
import shutil
from pathlib import Path
from random import uniform
from time import sleep
from typing import Pattern, Union

import requests
from bs4 import BeautifulSoup

from core_utils.article.article import Article
from core_utils.article.io import to_meta, to_raw
from core_utils.config_dto import ConfigDTO
from core_utils.constants import ASSETS_PATH, CRAWLER_CONFIG_PATH


class IncorrectSeedURLError(Exception):
    """
    Check seed URL does match or not standard pattern https?://(www.)?.
    """


class NumberOfArticlesOutOfRangeError(Exception):
    """
    Check total number of articles is out of range from 1 to 150 or not.
    """


class IncorrectNumberOfArticlesError(Exception):
    """
    Check total number of articles to parse is not integer or less than 0.
    """


class IncorrectHeadersError(Exception):
    """
    Check headers are in a form of dictionary or not.
    """


class IncorrectEncodingError(Exception):
    """
    Check that encoding must be specified as a string.
    """


class IncorrectTimeoutError(Exception):
    """
    Check that  timeout value must be a positive integer less than 60.
    """


class IncorrectVerifyError(Exception):
    """
    Check verify certificate value must either be ``True`` or ``False``.
    """


class Config:
    """
    Class for unpacking and validating configurations.
    """

    def __init__(self, path_to_config: pathlib.Path) -> None:
        """
        Initialize an instance of the Config class.

        Args:
            path_to_config (pathlib.Path): Path to configuration.
        """
        self.path_to_config = path_to_config
        config = self._extract_config_content()
        self._seed_urls = config.seed_urls
        self._num_articles = config.total_articles
        self._headers = config.headers
        self._encoding = config.encoding
        self._timeout = config.timeout
        self._should_verify_certificate = config.should_verify_certificate
        self._headless_mode = config.headless_mode
        self._validate_config_content()
        prepare_environment(ASSETS_PATH)

    def _extract_config_content(self) -> ConfigDTO:
        """
        Get config values.

        Returns:
            ConfigDTO: Config values
        """
        with open(self.path_to_config, 'r', encoding='utf-8') as file:
            config_data = json.load(file)
        return ConfigDTO(**config_data)

    def _validate_config_content(self) -> None:
        """
        Ensure configuration parameters are not corrupt.
        """
        if not isinstance(self._seed_urls, list) or not all(isinstance(url, str)
                                                            for url in self._seed_urls):
            raise IncorrectSeedURLError("Seed URL must be a string and be in the list")
        url_pattern = r'^(https?://(www\.)?zvezdaaltaya\.ru(/.*)?$)'
        if not all(re.match(url_pattern, url) for url in self._seed_urls):
            raise IncorrectSeedURLError("Seed URL must be a valid URL format")
        if (not isinstance(self._num_articles, int)
                or self._num_articles <= 0):
            raise (IncorrectNumberOfArticlesError
                   ("Total number of articles to parse is not an integer"))
        if self._num_articles > 150:
            raise (NumberOfArticlesOutOfRangeError
                   ("Total number of articles is out of range from 1 to 150"))
        if (not isinstance(self._headers, dict) or
                not all(isinstance(key, str) for key in self._headers.keys())
                or not all(isinstance(value, str) for value
                           in self._headers.values())):
            raise (IncorrectHeadersError
                   ("Headers must be presented as a dictionary with strings"))
        if not isinstance(self._encoding, str):
            raise IncorrectEncodingError("Encoding must be a string")
        if (not isinstance(self._timeout, int) or
                self._timeout not in range(1, 61)):
            raise IncorrectTimeoutError("Timeout is out of range - 60")
        if (not isinstance(self._headless_mode, bool) or
                not isinstance(self._should_verify_certificate, bool)):
            raise (IncorrectVerifyError
                   ("Headless mode and should_verify_certificate must be a bool"))

    def get_seed_urls(self) -> list[str]:
        """
        Retrieve seed urls.

        Returns:
            list[str]: Seed urls
        """
        return self._seed_urls

    def get_num_articles(self) -> int:
        """
        Retrieve total number of articles to scrape.

        Returns:
            int: Total number of articles to scrape
        """
        return self._num_articles

    def get_headers(self) -> dict[str, str]:
        """
        Retrieve headers to use during requesting.

        Returns:
            dict[str, str]: Headers
        """
        return self._headers

    def get_encoding(self) -> str:
        """
        Retrieve encoding to use during parsing.

        Returns:
            str: Encoding
        """
        return self._encoding

    def get_timeout(self) -> int:
        """
        Retrieve number of seconds to wait for response.

        Returns:
            int: Number of seconds to wait for response
        """
        return self._timeout

    def get_verify_certificate(self) -> bool:
        """
        Retrieve whether to verify certificate.

        Returns:
            bool: Whether to verify certificate or not
        """
        return self._should_verify_certificate

    def get_headless_mode(self) -> bool:
        """
        Retrieve whether to use headless mode.

        Returns:
            bool: Whether to use headless mode or not
        """
        return self._headless_mode


def make_request(url: str, config: Config) -> requests.models.Response:
    """
    Deliver a response from a request with given configuration.

    Args:
        url (str): Site url
        config (Config): Configuration

    Returns:
        requests.models.Response: A response from a request
    """
    request = requests.get(url, headers=config.get_headers(), timeout=config.get_timeout(),
                           verify=config.get_verify_certificate())
    request.encoding = config.get_encoding()
    sleep(uniform(0.000001, 0.1))
    return request


class Crawler:
    """
    Crawler implementation.
    """

    #: Url pattern
    url_pattern: Union[Pattern, str]

    def __init__(self, config: Config) -> None:
        """
        Initialize an instance of the Crawler class.

        Args:
            config (Config): Configuration
        """
        self.urls = []
        self.config = config

    def _extract_url(self, article_bs: BeautifulSoup) -> str:
        """
        Find and retrieve url from HTML.

        Args:
            article_bs (bs4.BeautifulSoup): BeautifulSoup instance

        Returns:
            str: Url from HTML
        """
        extracted_hrefs = {link['href'] for link in article_bs.find_all('a', href=True)}
        url_pattern = r'^(https?://(www\.)?zvezdaaltaya\.ru/\d{4}/\d{2}/.*)$'

        for url_href in extracted_hrefs:
            if (isinstance(url_href, str) and
                    re.match(url_pattern, url_href) and url_href not in self.urls):
                if not url_href.startswith('http'):
                    url_href = f"https://zvezdaaltaya.ru{url_href}"
                return url_href
        return ""

    def find_articles(self) -> None:
        """
        Find articles.
        """
        num = self.config.get_num_articles()
        seed_urls = self.config.get_seed_urls()

        for url in seed_urls:
            try:
                response = make_request(url, self.config)
            except requests.exceptions.RequestException:
                continue

            article_bs = BeautifulSoup(response.text, 'lxml')
            extracted_count = 0

            while extracted_count < num:
                article_url = self._extract_url(article_bs)
                if not article_url:
                    break
                if article_url not in self.urls:
                    self.urls.append(article_url)
                    extracted_count += 1
                else:
                    break
            if len(self.urls) >= num:
                break

    def get_search_urls(self) -> list:
        """
        Get seed_urls param.

        Returns:
            list: seed_urls param
        """
        return self.config.get_seed_urls()

# 10
# 4, 6, 8, 10


class HTMLParser:
    """
    HTMLParser implementation.
    """

    def __init__(self, full_url: str, article_id: int, config: Config) -> None:
        """
        Initialize an instance of the HTMLParser class.

        Args:
            full_url (str): Site url
            article_id (int): Article id
            config (Config): Configuration
        """
        self.full_url = full_url
        self.article_id = article_id
        self.config = config
        self.article = Article(full_url, article_id)

    def _fill_article_with_text(self, article_soup: BeautifulSoup) -> None:
        """
        Find text of article.

        Args:
            article_soup (bs4.BeautifulSoup): BeautifulSoup instance
        """
        all_body = article_soup.find_all("p")

        article_text = [block.get_text(strip=True) for block in all_body]
        full_text = ' '.join(article_text)
        self.article.text = full_text

    def _fill_article_with_meta_information(self, article_soup: BeautifulSoup) -> None:
        """
        Find meta information of article.

        Args:
            article_soup (bs4.BeautifulSoup): BeautifulSoup instance
        """
        title_element = article_soup.find("h1", class_="entry-title")
        self.article.title = (title_element.get_text
                                  (strip=True))

        authors = []

        spans_author = article_soup.find_all('span', style="color: #808080; font-size: 10pt;")
        text_author = article_soup.find_all('strong', attrs={"original-font-size": "15px"})
        left_author = article_soup.find_all('p', attrs={"style":"text-align: right;"})

        if spans_author:
            authors.append(spans_author[0].get_text(strip=True))
        if text_author:
            authors.append(text_author[0].get_text(strip=True))
        if left_author:
            authors.append(left_author[0].get_text(strip=True))

        if not authors:
            for p in article_soup.find_all(['p', 'div']):
                text = p.get_text(strip=True)
                if text.startswith("Фото:") or text.startswith("Информация/фото:"):
                    authors.append(text)
                    #break

        self.article.author = authors if authors else ["NOT FOUND"]

        try:
            published_time_meta = article_soup.find('meta', property='article:published_time')
            time = published_time_meta.get('content')
            self.article.date = self.unify_date_format(str(time)) if (
                time) else datetime.datetime.min
        except AttributeError:
            self.article.date = datetime.datetime.min

        categories = article_soup.find_all('ul', class_="td-tags td-post-small-box clearfix")
        self.article.topics = [a.get_text(strip=True) for category
                               in categories for a in category.find_all('a')]

    def unify_date_format(self, date_str: str) -> datetime.datetime:
        """
        Unify date format.

        Args:
            date_str (str): Date in text format

        Returns:
            datetime.datetime: Datetime object
        """

        date_part, time_part = date_str.split("T")
        time_part = time_part.split("+")[0]
        year, month, day = map(int, date_part.split("-"))
        hour, minute, second = map(int, time_part.split(":"))
        return datetime.datetime(year, month, day, hour, minute, second)

    def parse(self) -> Union[Article, bool, list]:
        """
        Parse each article.

        Returns:
            Union[Article, bool, list]: Article instance
        """
        response = make_request(self.full_url, self.config)
        if response.ok:
            data = response.content.decode(self.config.get_encoding())
            article_bs = BeautifulSoup(data, 'lxml')
            self._fill_article_with_text(article_bs)
            self._fill_article_with_meta_information(article_bs)
        return self.article


def prepare_environment(base_path: Union[pathlib.Path, str]) -> None:
    """
    Create ASSETS_PATH folder if no created and remove existing folder.

    Args:
        base_path (Union[pathlib.Path, str]): Path where articles stores
    """
    path = Path(base_path)
    if path.exists():
        if path.is_dir():
            shutil.rmtree(path, onerror=lambda func, path, excinfo:
            print(f"Error calling function {func.__name__} for path {path}: {excinfo}"))
    path.mkdir(parents=True, exist_ok=True)


def main() -> None:
    """
    Entrypoint for scrapper module.
    """
    config = Config(CRAWLER_CONFIG_PATH)
    crawler = Crawler(config)
    prepare_environment(ASSETS_PATH)
    crawler.find_articles()
    for identifier, url in enumerate(crawler.urls, start=1):
        parser = HTMLParser(url, identifier, config)
        article = parser.parse()
        if isinstance(article, Article):
            to_raw(article)
            to_meta(article)


if __name__ == "__main__":
    main()

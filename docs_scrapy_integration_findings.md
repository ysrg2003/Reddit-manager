# Scrapy integration findings

## What the linked repository provides

The linked `ysrg2003/scrapy` repository is the general Scrapy framework. It does not contain a ready-made Reddit spider or a Reddit API adapter. Reddit-specific selectors and crawl logic must be implemented in Reddit-manager.

## Safe integration design

Scrapy can parse the HTML returned by ScraperAPI using CSS/XPath selectors and can run a spider programmatically. The first stage can parse the old Reddit search HTML and extract multiple post permalinks. The second stage can request each post page through ScraperAPI and parse post text and comment elements if those elements are actually present in the returned HTML.

Scrapy cannot convert HTML into Reddit JSON, recover content that is not present in the response, or defeat a Reddit challenge page by itself. If the post page returned by ScraperAPI is a challenge/shell page, the evidence collector must report `content_unavailable` rather than inventing post text or comments.

## Official references

- https://docs.scrapy.org/en/latest/topics/selectors.html — CSS/XPath selectors and `Selector` parsing.
- https://docs.scrapy.org/en/latest/topics/practices.html — running Scrapy spiders programmatically.
- https://docs.scrapy.org/en/latest/intro/overview.html — spiders, asynchronous requests, feed exports, and crawl controls.

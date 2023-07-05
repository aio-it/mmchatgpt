import newspaper
from markdownify import markdownify as md

def fetch_and_parse(url):
    # Create a new article object
    article = newspaper.Article(url)

    # Download and parse the article
    article.download()
    article.parse()

    # Get the markdown content from the parsed HTML article
    markdown_content = md(article.text)

    return markdown_content


def return_urls_from_news_site(site: str):
    # Return a list of urls from a news site
    # fetch paper from newspaper3k
    article_urls = []
    try:
        paper = newspaper.build(site, memoize_articles=False)
        for article in paper.articles:
            article_urls.append(article.url)
        return article_urls
    except:
        return article_urls

def extract_from_website_using_newspaper(url: str):
    """return a string with fulltext from a url"""
    article = newspaper.Article(url)
    article.download()
    article.parse()
    return article
def extract_from_website_using_beautifulsoup(url: str):
    """return a string with paragraphs and h1-h5 from a url"""
    from bs4 import BeautifulSoup
    import requests
    page = requests.get(url)
    soup = BeautifulSoup(page.content, 'html.parser')
    # remove all script and style elements
    for script in soup(["script", "style","head"]):
        script.decompose()    # rip it out
    # all elements and extract elements that contain "text"
    strip = [r'nav',r'head', r'foot',r'menu']
    import re
    found_elements = []
    for elem in soup.find_all():
        # find items with class attribute that contains "text"
        #print(elem.attrs)
        for s in strip:
            if elem.has_attr('class'):
                for _class in elem['class']:
                    if re.search(s, _class) is not None:
                        #print(f"found {s} in {_class}")
                        found_elements.append(elem)
                        continue
    for elem in found_elements:
        elem.decompose()
    del found_elements
    # get text
    text = soup.get_text()
    # break into lines and remove leading and trailing space on each
    lines = (line.strip() for line in text.splitlines())
    # break multi-headlines into a line each
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    # drop blank lines
    text = '\n'.join(chunk for chunk in chunks if chunk)
    class article:
        def __init__(self, title, text, keywords=[], authors=[]):
            self.title = title
            self.text = text
            self.summary = text[:100]
            self.keywords = keywords
            self.authors = authors
    bsarticle = article("", text)
    return bsarticle

# Test function:
#url = "https://medium.com/macoclock/9-new-must-have-macos-productivity-apps-for-daily-usage-fec955b1510c"
#content = fetch_and_parse(url)
#print(content)

#article = extract_from_website_using_newspaper(url)
#print(f"{article.title}: {article.summary} by {article.authors} keywords: {','.join(article.keywords)}\n{article.text}")
def compare_extract(url: str):
    articlenp = extract_from_website_using_newspaper(url)
    articlebs = extract_from_website_using_beautifulsoup(url)

    print("np article:")
    print(articlenp.text)
    print("bs article:")
    print(articlebs.text)

    print(f"np len: {len(articlenp.text)}")
    print(f"bs len: {len(articlebs.text)}")

url = "https://www.dr.dk/nyheder/"
#urls = return_urls_from_news_site(url)
#print(urls)

#url = "https://www.dr.dk/nyheder/seneste/gennemsnitstemperatur-maalt-til-det-hoejeste-nogensinde-anden-dag-i-traek"
#url = "https://docs.aws.amazon.com/IAM/latest/UserGuide/console_search.html"
url = "https://ekstrabladet.dk/nyheder/samfund/soedestof-paa-kraeftliste-slut-med-coca-cola-zero/9847762"
#url = "https://stackoverflow.com/questions/36724209/disable-beep-in-wsl-terminal-on-windows-10"
#url = "https://github.com/microsoft/WSL/issues/715#issuecomment-238010146"
#for url in urls:
compare_extract(url)

import httpx
from bs4 import BeautifulSoup

async def fetch_article_text(url: str, id: str) -> tuple[str, str, str]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract plain text
            for script in soup(["script", "style"]):
                script.extract()
            text = soup.get_text(separator=' ')

            # Trim to max 2000 characters for token efficiency
            trimmed_text = text[:10000].strip()

            if not trimmed_text:
                return (id, url, "")

            # sanitize the text by removing all non-printable characters and
            # break lines new lines
            trimmed_text = ''.join(c for c in trimmed_text if c.isprintable())

            return (id, url, trimmed_text)

    except Exception as e:
        print(f"Failed to fetch article text {url}: {e}")
        return (id, url, "")

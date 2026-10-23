"""robots.txt support using Protego, an RFC 9309 compliant parser.

Python's built-in urllib.robotparser applies the first matching rule and
ignores wildcards, which wrongly disallowed sites such as google.com.
"""

import httpx
from protego import Protego

ROBOTS_TOKEN = "mini-technographics"
MAX_ROBOTS_CHARS = 512 * 1024


async def is_allowed(client: httpx.AsyncClient, domain: str, path: str = "/") -> bool:
    """Return False only when robots.txt (or the server) tells us to stay away.

    Conventions, similar to major search engines:
    - 2xx: parse the rules
    - 429 and 5xx: treat the site as disallowed, the server asks us to back off
    - other 4xx: no robots.txt, everything is allowed
    - network errors: allowed; the homepage fetch will classify the failure
    """
    try:
        response = await client.get(f"https://{domain}/robots.txt")
    except httpx.HTTPError:
        return True
    status = response.status_code
    if status == 429 or status >= 500:
        return False
    if status >= 400:
        return True
    rules = Protego.parse(response.text[:MAX_ROBOTS_CHARS])
    return rules.can_fetch(f"https://{domain}{path}", ROBOTS_TOKEN)

import requests
from typing import List
from .mw import ProxyMiddleware, Proxy
from .adapter import ProxyAdapter

requests.packages.urllib3.disable_warnings()


def init_session(
    proxies: List[Proxy], retry_on_exceptions: set = (), retry_on_status_codes: set = ()
) -> requests.Session:
    proxy_mw = ProxyMiddleware(proxies=proxies,)

    adapter = ProxyAdapter(
        proxy_mw=proxy_mw,
        retry_on_exceptions=retry_on_exceptions,
        retry_on_status_codes=retry_on_status_codes,
    )
    http = requests.Session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)
    http.verify = False
    return http

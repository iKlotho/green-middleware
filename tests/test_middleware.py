from greenmw import Proxy, init_session

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/85.0.4183.102 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.5",
    "X-Requested-With": "XMLHttpRequest",
}


def test_setup():
    proxies = [
        Proxy(address="http://10.219.162.67:3128", headers=headers,),
    ]
    session = init_session(proxies=proxies)
    response = session.get("https://httpbin.org/json")
    assert response.ok is True
    assert response.proxy.address is proxies[0].address


def test_failover():
    proxies = [
        Proxy(address="http://10.219.162.67:3128", headers=headers,),
        Proxy(address="http://10.219.162.67:3129", headers=headers,),
    ]
    session = init_session(proxies=proxies)
    session.get("https://httpbin.org/status/403")
    # both adapters are same pick one
    adapter = list(session.adapters.items())[0][1]
    # both proxies should be dead
    assert len(adapter.proxy_mw.dead) == 2

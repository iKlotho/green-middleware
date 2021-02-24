import attr
import gevent
import math
import time
import logging
import hashlib
import random
from itertools import cycle

try:
    from gevent.coros import BoundedSemaphore
except:
    from gevent.lock import BoundedSemaphore

log = logging.getLogger(__name__)


def generate_uuid(proxy):
    """
        Generate v4 uuid for device
    """
    return hashlib.md5(proxy.encode("utf-8")).hexdigest()


@attr.s
class Proxy:
    address: str = attr.ib()
    formatted: dict = attr.ib(init=False, repr=False)
    failed_attempts: int = attr.ib(default=0)
    dead: bool = attr.ib(default=False)
    headers: dict = attr.ib(default={})
    next_check = attr.ib(default=None)
    uuid: str = attr.ib(init=False)
    header_hook: callable = attr.ib(default=None)
    device: str = attr.ib(default="")
    used: int = attr.ib(default=0)

    def __attrs_post_init__(self):
        print("Proxy attr", self.headers)
        append = ""
        if "X-ProxyMesh-IP" in self.headers.keys():
            append = self.headers["X-ProxyMesh-IP"]
            print("Xproxy in header ", append)

        if "X-ProxyMesh-Prefer-IP" in self.headers.keys():
            append = self.headers["X-ProxyMesh-Prefer-IP"]
            print("Xproxy in header ", append)

        self.uuid = generate_uuid(self.address + append)
        # TODO check if address has http
        self.formatted = {"http": self.address, "https": self.address}


@attr.s
class ProxyMiddleware:
    proxies: list = attr.ib(default=[], repr=False)
    _proxies: dict = attr.ib(default={}, init=False, repr=False)
    unchecked: set = attr.ib(default=set())
    dead: set = attr.ib(default=set())
    good: set = attr.ib(default=set())
    backoff: callable = attr.ib(init=False)
    total_requests: int = attr.ib(default=0)
    # rotate every 2000 rqeuests 
    rotate_every_request: int = attr.ib(default=2000)
    sem = attr.ib(init=False)
    mesh = attr.ib(repr=False, default=None)
    locations = attr.ib(init=False)
    # inting proxyis
    proxy_init = attr.ib(default=None)
    # if changed already
    changed: bool = attr.ib(default=False)

    def __attrs_post_init__(self):
        log.info("PROXY Middleware initialized!")
        self.locations = cycle(( "fr", "de", "au", "sg", "nl", "uk", ))
        self.sem = BoundedSemaphore(1)
        self.backoff = exp_backoff_full_jitter
        self.init_proxies(self.proxies)

    def init_proxies(self, proxies: list) -> None:
        """
            Reset proxy checkers and set new ones
        """
        self._proxies = {}
        self.dead = set()
        self.good = set()
        self.unchecked = set()
        for proxy in proxies:
            self._proxies[proxy.uuid] = proxy
            self.unchecked.add(proxy.uuid)
        self.reset()

    def set_new_proxies(self) -> None:
        """
            Set new proxy for new country in cycle
        """
        log.info("Changing the proxy %s ", self.mesh)
        if self.mesh:
            log.info("Changing the proxy sleep for 5 seconds")
            gevent.sleep(5) #waiting 5 seconds to other connection finish?
            log.info("Proxy changed %s", self.changed)
            if not self.changed:
                country = self.locations.__next__()
                if country == self.mesh.active_country:
                    country = self.locations.__next__()
                    print("country is alread active get new", country)
                self.mesh.change_location(country)
                try:
                    proxies = self.mesh.get_proxies(country)
                except Exception as e:
                    print("error while geting new ips", str(e))
                    self.set_new_proxies()
                    return True

                proxy_list = [
                    self.proxy_init(proxy)
                    for proxy in proxies
                ]
                self.init_proxies(proxy_list)
                self.changed = True
                log.info("Changed country to %s", country)
            return True
        return False

    def get_proxy(self, which="open") -> Proxy:
        with self.sem:
            self.total_requests += 1
            if self.total_requests % self.rotate_every_request == 0:
                print("set the proxy")
                self.set_new_proxies()

            if not self.available:
                if self.set_new_proxies():
                    return self.get_proxy()
                return None
            proxy = self._proxies[random.choice(self.available)]
            proxy.used += 1
            return proxy

    def reanimate(self, _time=None) -> None:
        """ Move dead proxies to unchecked if a backoff timeout passes """
        self.changed = False
        now = _time if _time is not None else time.time()
        for pkey in list(self.dead):
            state = self._proxies[pkey]
            if state.next_check is not None and state.next_check <= now:
                log.info("Animated a proxy %s", pkey)
                self.dead.remove(pkey)
                self.unchecked.add(pkey)

    @property
    def available(self):
        """
            Return list of available proxies
        """
        return list(self.unchecked | self.good)

    def mark_proxy_dead(self, proxy: Proxy) -> None:
        self.sem.acquire()
        self.dead.add(proxy.uuid)
        self.good.discard(proxy.uuid)
        self.unchecked.discard(proxy.uuid)
        now = time.time()
        proxy.dead = True
        proxy.backoff_time = self.backoff(proxy.failed_attempts)
        proxy.next_check = now + proxy.backoff_time
        proxy.failed_attempts += 1
        log.info("proxy marked bad %s", proxy)
        self.sem.release()

    def mark_proxy_good(self, proxy: Proxy) -> None:
        self.sem.acquire()
        self.good.add(proxy.uuid)
        self.unchecked.discard(proxy.uuid)
        self.bad.discard(proxy.uuid)
        proxy.failed_attempts = 0
        proxy.dead = False
        log.info("proxy marked good %s", proxy)
        self.sem.release()

    def reset(self):
        for proxy in self.proxies:
            self.unchecked.add(proxy.uuid)
            self.dead.discard(proxy.uuid)


def exp_backoff(attempt, cap=36, base=5):
    """ Exponential backoff time """
    # this is a numerically stable version of
    # min(cap, base * 2 ** attempt)
    max_attempts = math.log(cap / base, 2)
    if attempt <= max_attempts:
        return base * 2 ** attempt
    return cap


def exp_backoff_full_jitter(*args, **kwargs):
    """ Exponential backoff time with Full Jitter """
    return random.uniform(0, exp_backoff(*args, **kwargs) - 5)


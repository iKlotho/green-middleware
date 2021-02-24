import attr
import uuid
import gevent
import math
import time
from loguru import logger
import random
from itertools import cycle

try:
    from gevent.coros import BoundedSemaphore
except:
    from gevent.lock import BoundedSemaphore


@attr.s
class Proxy:
    address: str = attr.ib()
    formatted: dict = attr.ib(init=False, repr=False)
    _id: uuid.uuid4 = attr.ib(default=attr.Factory(uuid.uuid4))
    failed_attempts: int = attr.ib(default=0)
    dead: bool = attr.ib(default=False)
    headers: dict = attr.ib(default={})
    next_check = attr.ib(default=None)
    header_hook: callable = attr.ib(default=None)
    device: str = attr.ib(default="")
    used: int = attr.ib(default=0)

    def __attrs_post_init__(self):
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
    locations = attr.ib(init=False)
    # if changed already
    changed: bool = attr.ib(default=False)

    def __attrs_post_init__(self):
        logger.info("PROXY Middleware initialized!")
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
            self._proxies[proxy._id] = proxy
            self.unchecked.add(proxy._id)
        self.reset()

    def set_new_proxies(self) -> None:
        """
        Set new proxy for new country in cycle
        """
        logger.info("Changing the proxy %s ", self.mesh)
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
                logger.info(f"Animated a proxy {pkey}")
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
        self.dead.add(proxy._id)
        self.good.discard(proxy._id)
        self.unchecked.discard(proxy._id)
        now = time.time()
        proxy.dead = True
        proxy.backoff_time = self.backoff(proxy.failed_attempts)
        proxy.next_check = now + proxy.backoff_time
        proxy.failed_attempts += 1
        logger.info(f"proxy marked bad {proxy.address}")
        self.sem.release()

    def mark_proxy_good(self, proxy: Proxy) -> None:
        self.sem.acquire()
        self.good.add(proxy._id)
        self.unchecked.discard(proxy._id)
        self.bad.discard(proxy._id)
        proxy.failed_attempts = 0
        proxy.dead = False
        logger.info(f"proxy marked good {proxy.address}")
        self.sem.release()

    def reset(self):
        for proxy in self.proxies:
            self.unchecked.add(proxy._id)
            self.dead.discard(proxy._id)


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

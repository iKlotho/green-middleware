from logging import exception
import ssl
import orjson
import cchardet
import traceback
from loguru import logger
from requests.adapters import HTTPAdapter
from .exceptions import ServerErrorException, StatusCodeException
from .retry import retry


class ProxyAdapter(HTTPAdapter):
    DEFAULT_POOLBLOCK = False
    DEFAULT_POOLSIZE = 100
    DEFAULT_RETRIES = 0
    DEFAULT_POOL_TIMEOUT = None

    def __init__(
        self,
        pool_connections=DEFAULT_POOLSIZE,
        pool_maxsize=DEFAULT_POOLSIZE,
        max_retries=DEFAULT_RETRIES,
        pool_block=DEFAULT_POOLBLOCK,
        proxy_mw=None,
        retry_on_exceptions=(Exception,),  # retry on everything
        retry_on_status_codes=(400, 403, 407, 408, 429, 499,),
        tries=3,
        delay=1,
        backoff=2,
        max_delay=4,
        jitter=0,
    ):
        self.proxy_mw = proxy_mw
        self.retry_on_exceptions = retry_on_exceptions
        self.retry_on_status_codes = retry_on_status_codes
        if self.retry_on_status_codes:
            self.retry_on_exceptions += (StatusCodeException,)
        self.tries = tries
        self.delay = delay
        self.backoff = backoff
        self.max_delay = max_delay
        self.jitter = jitter
        super(ProxyAdapter, self).__init__()

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        """Called to initialize the HTTPAdapter when no proxy is used."""
        try:
            pool_kwargs["ssl_version"] = ssl.PROTOCOL_TLS
        except AttributeError:
            pool_kwargs["ssl_version"] = ssl.PROTOCOL_SSLv23
        return super(ProxyAdapter, self).init_poolmanager(
            connections, maxsize, block, **pool_kwargs
        )

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        """Called to initialize the HTTPAdapter when a proxy is used."""
        try:
            proxy_kwargs["ssl_version"] = ssl.PROTOCOL_TLS
        except AttributeError:
            proxy_kwargs["ssl_version"] = ssl.PROTOCOL_SSLv23
        return super(ProxyAdapter, self).proxy_manager_for(proxy, **proxy_kwargs)

    def proxy_headers(self, proxy):
        headers = super(ProxyAdapter, self).proxy_headers(proxy)
        # key = generate_pid(proxy)
        # proxy_cls = self.proxy_mw._proxies[key]
        # if hasattr(proxy_cls, 'header_hook') and proxy_cls.header_hook is not None:
        #     new_headers = proxy_cls.header_hook(proxy_cls.uuid, proxy_cls.device)
        #     headers.update(new_headers)
        # headers.update(proxy_cls.headers)
        # log.debug("new headers %s", headers)
        return headers

    def add_headers(self, request, **kwargs):
        """Add any headers needed by the connection. As of v2.0 this does
        nothing by default, but is left for overriding by users that subclass
        the :class:`HTTPAdapter <requests.adapters.HTTPAdapter>`.

        This should not be called from user code, and is only exposed for use
        when subclassing the
        :class:`HTTPAdapter <requests.adapters.HTTPAdapter>`.

        :param request: The :class:`PreparedRequest <PreparedRequest>` to add headers to.
        :param kwargs: The keyword arguments from the call to send().
        """
        proxy_cls = request.proxy
        if hasattr(proxy_cls, "header_hook") and proxy_cls.header_hook is not None:
            new_headers = proxy_cls.header_hook(proxy_cls.uuid, proxy_cls.device)
            request.headers.update(new_headers)
        request.headers.update(proxy_cls.headers)
        return request.headers

    def build_response(self, req, resp):
        """ Catch html status codes from here to mark proxy dead """
        response = super().build_response(req, resp)
        if response.encoding is None:
            # Requests detects the encoding when the item is GET'ed using
            # HTTP headers, and then when r.text is accessed, if the encoding
            # hasn't been set by that point. By setting the encoding here, we
            # ensure that it's done by cchardet, if it hasn't been done with
            # HTTP headers. This way it is done before r.text is accessed
            # (which would do it with vanilla chardet). This is a big
            # performance boon.
            response.encoding = cchardet.detect(response.content)["encoding"]
        if response.status_code in self.retry_on_status_codes:
            if self.proxy_mw:
                self.proxy_mw.mark_proxy_dead(req.proxy)
            raise StatusCodeException(response.status_code)
        # TODO this will only work for sahi
        try:
            # data = response.orjson()
            data = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            data = response.content
        except Exception as e:
            data = {"success": "false"}
            logger.warning(
                f"error woot {str(e)} - response raw {req.url} - body {req.body}"
            )
            print(traceback.format_exc())
            if self.proxy_mw:
                self.proxy_mw.mark_proxy_dead(req.proxy)

        response.data = data
        response.proxy = req.proxy

        if str(response.status_code)[0] == "5":
            # stop the code
            self.proxy_mw.mark_proxy_dead(req.proxy)
            # raise ServerErrorException
        return response

    @retry
    def send(
        self, request, stream=False, timeout=None, verify=False, cert=None, proxies=None
    ):
        proxy = self.proxy_mw.get_proxy()
        if not proxy:
            logger.warning("No proxies available; resetting all proxies!")
            self.proxy_mw.reset()
            proxy = self.proxy_mw.get_proxy()
            if not proxy:
                raise Exception("No Proxy Available after reset()")
        proxies = proxy.formatted
        proxy_cls = request.proxy = proxy
        # log.debug("using proxy %s", proxy)
        request.headers.update(proxy_cls.headers)
        if hasattr(proxy_cls, "header_hook") and proxy_cls.header_hook is not None:
            new_headers = proxy_cls.header_hook(proxy_cls.uuid, proxy_cls.kwargs)
            request.headers.update(new_headers)

        logger.debug(f"headersss {request.headers}")

        try:
            return super(ProxyAdapter, self).send(
                request, stream, timeout, verify, cert, proxies
            )
        except Exception as e:
            if self.proxy_mw:
                self.proxy_mw.mark_proxy_dead(request.proxy)
            raise e

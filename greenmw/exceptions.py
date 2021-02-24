class ServerErrorException(Exception):
    """ Used when the response status code is 5xx"""

    pass


class StatusCodeException(Exception):
    """ Used when the response status code is in retried codes"""

    pass


class ProxyError(Exception):
    pass

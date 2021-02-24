class ServerErrorException(Exception):
    """ Used when the response status code is 5xx"""
    pass

class ProxyError(Exception):
    pass
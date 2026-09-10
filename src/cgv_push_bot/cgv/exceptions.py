class CgvError(Exception):
    pass


class CgvTransportError(CgvError):
    pass


class CgvApiError(CgvError):
    pass


class CgvResponseError(CgvError):
    pass

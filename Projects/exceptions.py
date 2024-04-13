class InvalidPDUException(Exception):
    def __init__(self, message="Invalid PDU"):
        super().__init__(message)


class NACKException(Exception):
    def __init__(self, message="NACK"):
        super().__init__(message)


class NoConnectionException(Exception):
    def __init__(self, message="No existing such connection"):
        super().__init__(message)


class LimitSentAttemptsException(Exception):
    def __init__(self, message="Too many attempts to send a frame"):
        super().__init__(message)


class Timeout(Exception):
    def __init__(self, message="timeout!"):
        super().__init__(message)


class ExistingConnectionException(Exception):
    def __init__(self, message="Connection with this server already exists"):
        super().__init__(message)

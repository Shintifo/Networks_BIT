class InvalidPDUException(Exception):
    def __init__(self, message="Invalid PDU"):
        super().__init__(message)

class NACKException(Exception):
    def __init__(self, message="NACK"):

        super().__init__(message)


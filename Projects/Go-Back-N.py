import zlib
from threading import Thread
from socket import socket, AF_INET, SOCK_DGRAM, timeout

from exceptions import InvalidPDUException, NACKException

# TODO header size
MESSAGE_SIZE = 10
CHECKSUM_SIZE = 4  # bytes
FRAME_SIZE = CHECKSUM_SIZE + MESSAGE_SIZE
TIMER = 2
STANDARD_WS = 3
CONNECTION_ATTEMPTS = 5
HOST1_ADDR = ('127.0.0.1', 5555)
HOST2_ADDR = ('127.0.0.1', 8888)



# Отправляем сообщение\файл
# 1. Хендшейк -> размер окна
# 2. Отправляем начальный пакет -> (start|size|checksum)
# 3. Отправляем данные пока размер не будет что надо (
#       файл - также как в DNP
#       сообщение временная переменная, вывод сразу после получение и unlock user keyboard)
# 4.
# 5.


class PDU:
    def __init__(self, data=None):
        self.data: bytes = data
        self.size = MESSAGE_SIZE
        self.checksum = b''
        if self.data is not None:
            self.size = len(self.data) - CHECKSUM_SIZE
            self.message = self.data[:self.size]
            self.checksum = self.data[self.size:]

    def calc_checksum(self, data):
        return zlib.adler32(data).to_bytes(CHECKSUM_SIZE, byteorder='big')

    def pack(self, data):
        # TODO (type|data|checksum)
        # TODO header -> seqnum -> number of frame
        # TODO how to define number of bytes

        encoded_data = data.encode('utf-8')
        self.size = len(encoded_data)
        self.checksum = self.calc_checksum(encoded_data)
        self.data = encoded_data + self.checksum

    def check(self):
        cal_checksum = self.calc_checksum(self.message)
        return cal_checksum == self.checksum

    def unpack(self) -> str:
        # TODO decode files
        if not self.check():
            raise InvalidPDUException("Checksum mismatch!")
        message = self.data[:self.size].decode('utf-8')
        return message

    def get_bytes(self):
        return self.data


# TODO close socket
class Socket:
    def __init__(self, home_address, address):
        self.sock = socket(AF_INET, SOCK_DGRAM)
        self.sock.settimeout(TIMER)
        self.sock.bind(home_address)
        self.receiver_address = address

    def recframe(self):
        try:
            data, addr = self.sock.recvfrom(FRAME_SIZE)
            frame = PDU(data)
            message = frame.unpack()
            return message
        except InvalidPDUException as e:
            print(e)
            raise NACKException()

    def send(self, frame: PDU):
        self.sock.sendto(frame.data, self.receiver_address)


class Host:
    def __init__(self, address, ws=STANDARD_WS):
        self.address = address
        self.connections: {str: Socket} = {}
        self.ws = ws
        self.receive_thread = None

    def add_connection(self, host_address):
        self.connections[host_address] = Socket(self.address, host_address)
        self.receive_thread = Thread(target=self.receive, args=(host_address,))
        self.receive_thread.start()

    def receive(self, host_address):
        # TODO: как понять что сообщение закончилосб? Seqno???
        try:
            while True:
                try:
                    data = self.connections[host_address].recframe()
                    print(data)
                    self.connections[host_address].send(ACK_FRAME)
                except timeout:
                    # print("Didn't receive any")
                    # TODO
                    pass

        except KeyboardInterrupt:
            print("Shutting down...")
            exit()

    def start_frame(self, message_size):
        frame = PDU()
        frame.pack(message_size)



    def send_message(self, message, address):
        # TODO check existing connection -> raise error
        # TODO Send first frame as begging of the message

        # Made to send WS --- КОСТЫЛЬ
        if type(message) is int:
            message = str(message)

        self.start_frame(len(message))


        i = 0
        # TODO chunk size
        while i < len(message):
            k = i * MESSAGE_SIZE
            chunk = message[k:k + MESSAGE_SIZE]
            frame = PDU()
            frame.pack(chunk)
            try:
                self.connections[address].send(frame)
                self.await_ack(address)
                i += MESSAGE_SIZE
            except NACKException:
                raise ConnectionRefusedError

    def await_ack(self, address):
        try:
            data = self.connections[address].recframe()
            if data != "ACK":
                raise NACKException
            print("ACK!")
        except timeout:
            raise NACKException
            # TODO
            print("Timeout")


class Connector:
    def __init__(self):
        print("Connector started!")

    def create_connection(self, host1: Host, host2: Host):
        # Make connection between hosts
        # And send WS to each other
        host1.add_connection(host2.address)
        host2.add_connection(host1.address)

        try:
            self.handshake()
        except ConnectionRefusedError:
            raise ConnectionRefusedError

    def handshake(self):
        attempts = 0
        try:
            print("SYNC1")
            host1.send_message(host1.ws, host2.address)
            print("SYNC2")
            host2.send_message(host2.ws, host1.address)
            print("Successful Handshake!")
        except ConnectionRefusedError:
            if attempts == CONNECTION_ATTEMPTS:
                raise ConnectionRefusedError
            attempts += 1


ACK_FRAME = PDU()
ACK_FRAME.pack("ACK")

if __name__ == '__main__':
    host1 = Host(HOST1_ADDR, ws=4)
    host2 = Host(HOST2_ADDR, ws=5)

    connector = Connector()

    try:
        connector.create_connection(host1, host2)
    except ConnectionRefusedError:
        print("No Connection")

import os
import zlib
from enum import Enum
from threading import Thread, Event
from socket import socket, AF_INET, SOCK_DGRAM, timeout

from exceptions import InvalidPDUException, NACKException, NoConnectionException, LimitSentAttemptsException

# TODO header size
HEADER_SIZE = 1
MESSAGE_SIZE = 10
CHECKSUM_SIZE = 4  # bytes
FRAME_SIZE = HEADER_SIZE + CHECKSUM_SIZE + MESSAGE_SIZE
TIMER = 2
STANDARD_WS = 3
CONNECTION_ATTEMPTS = 5
TIMEOUT_NUMBER = 5
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


class FrameType(Enum):
    HANDSHAKE = 0
    START = 1
    DATA = 2
    ACK = 3


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
        # TODO how to define number of bytes for checksum????
        return zlib.adler32(data).to_bytes(CHECKSUM_SIZE, byteorder='big')

    def pack(self, data: str | bytes, frame_type: FrameType):
        def make_header():
            header = b''
            match frame_type:
                case FrameType.HANDSHAKE:
                    header = b'h|'
                case FrameType.START:
                    header = b's|'
                case FrameType.DATA:
                    header = b'd|'
                case FrameType.ACK:
                    header = b''
            return header + data

        data = data.encode('utf-8') if type(data) is str else data
        data = make_header()

        self.checksum = self.calc_checksum(data)
        self.data = data + self.checksum
        return self

    def check(self):
        cal_checksum = self.calc_checksum(self.message)
        return cal_checksum == self.checksum

    def unpack(self) -> bytes:
        if not self.check():
            raise InvalidPDUException("Checksum mismatch!")
        message = self.data[:self.size]
        return message


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
        self.hosts_ws: {str: int} = {}
        self.receive_thread = None
        self.files = {}
        self.ack_event = Event()

    def add_connection(self, host_address):
        self.connections[host_address] = Socket(self.address, host_address)
        self.receive_thread = Thread(target=self.receive, args=(host_address,))
        self.receive_thread.start()

    def handle_message(self, message: bytes, sender_address):
        # TODO ADD SMTH DATA TO WS
        # handshake: header|WS
        # start:     header|filename|file_size
        # data:      header|seqno|data
        header = message[:HEADER_SIZE]

        match header:
            case FrameType.HANDSHAKE:
                _, ws = message.split(b'|', 1)
                self.hosts_ws[sender_address] = int(ws.decode())
            case FrameType.START:
                _, filename, file_size = message.split(b'|', 2)
                file_path = os.path.join(os.getcwd(), filename.decode())

                if os.path.exists(file_path):
                    os.remove(file_path)

                self.files[sender_address] = {
                    "file": open(file_path, 'wb'),
                    "size": int(file_size.decode),
                    "seqno": 0,
                    "rec_size": 0
                }
            case FrameType.DATA:
                _, seqno, data = message.split(b'|', 2)
                seqno = int(seqno.decode())

                if seqno != self.files[sender_address]["seqno"]:
                    return

                self.files[sender_address]["seqno"] += 1
                self.files[sender_address]["file"].write(data)
                self.files[sender_address]["rec_size"] += len(data)

                if self.files[sender_address]["rec_size"] == self.files[sender_address]["size"]:
                    self.files[sender_address]["file"].close()
                    self.files.pop(sender_address)

    def receive(self, host_address):
        # TODO conflict with await_ack
        timeouts_number = 0
        try:
            while True:
                try:
                    data = self.connections[host_address].recframe()
                    self.handle_message(data, host_address)
                    self.connections[host_address].send(ACK_FRAME)
                    timeouts_number = 0
                except timeout:
                    if timeouts_number == TIMEOUT_NUMBER:
                        #  TODO Break connection
                        print("Break the connection!")
                    timeouts_number += 1
        except KeyboardInterrupt:
            print("Shutting down...")
            exit()
            # TODO handle threads

    def send_frame(self, data, frame_type, address):
        attempts = 0
        frame = PDU().pack(data, frame_type)

        try:
            self.connections[address].send(frame)
            self.await_ack(address)
        except NACKException:
            if attempts == CONNECTION_ATTEMPTS:
                raise LimitSentAttemptsException
            attempts += 1

    def send_sync(self, ws, address):
        if address not in self.connections:
            raise NoConnectionException
        self.send_frame(ws, FrameType.HANDSHAKE, address)

    def send_file(self, file, address):
        # Sends files or WS for Handshake
        if address not in self.connections:
            raise NoConnectionException

        try:
            file_size = os.path.getsize(file)
            self.send_frame(f"{file}|{file_size}", FrameType.START, address)

            data_chunks = []
            with open(file, "rb") as f:
                for i in range((file_size + MESSAGE_SIZE - 1) // MESSAGE_SIZE):
                    data = f.read(MESSAGE_SIZE)
                    seqno = i % self.ws
                    data_chunks.append(f"{seqno}|{data}")

            wait_frames_ack = 0
            while i != len(data_chunks):
                if wait_frames_ack == self.ws:
                    self.ack_event.wait()
                    self.ack_event.clear()
                    wait_frames_ack -= 1

                self.send_frame(data_chunks[i], FrameType.DATA, address)
                wait_frames_ack += 1
                i += 1
        except LimitSentAttemptsException:
            raise LimitSentAttemptsException

    def await_ack(self, address):
        # TODO conflict with receive
        try:
            data = self.connections[address].recframe()
            if data not in ("SYNACK", "ACK"):
                raise NACKException
            print(data)
        except timeout:
            raise NACKException


class Connector:
    def __init__(self):
        pass

    def create_connection(self, host1: Host, host2: Host):
        # Make connection between hosts
        # And send WS to each other as handshake
        host1.add_connection(host2.address)
        host2.add_connection(host1.address)
        self.handshake()

    def handshake(self):
        host1.send_sync(str(host1.ws), host2.address)
        print("SYNC1")
        host2.send_sync(str(host2.ws), host1.address)
        print("SYNC2")
        print("Successful Handshake!")


ACK_FRAME = PDU()
ACK_FRAME.pack("ACK", FrameType.ACK)

# TODO User Input
if __name__ == '__main__':
    host1 = Host(HOST1_ADDR, ws=4)
    host2 = Host(HOST2_ADDR, ws=5)

    connector = Connector()

    try:
        connector.create_connection(host1, host2)
    except LimitSentAttemptsException:
        print("No Connection established")

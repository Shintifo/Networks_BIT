import datetime
import os
import time
import zlib
from enum import Enum
from threading import Thread, Event
from socket import socket, AF_INET, SOCK_DGRAM, timeout

from exceptions import InvalidPDUException, NACKException, NoConnectionException, \
    LimitSentAttemptsException, Timeout, ExistingConnectionException

# NOTE: I consider that between 2 hosts we can create only 1 connection
#       and host1 cannot send 2 files in parallel to host2

# TODO change const
TIMER_ACK = 5
TIMER = 2

CONNECTION_ATTEMPTS = 5
TIMEOUT_NUMBER = 5

HEADER_SIZE = 1
MESSAGE_SIZE = 10
CHECKSUM_SIZE = 4
FRAME_SIZE = HEADER_SIZE + CHECKSUM_SIZE + MESSAGE_SIZE

STANDARD_WS = 3
HOST1_ADDR = ('127.0.0.1', 5555)
HOST2_ADDR = ('127.0.0.1', 8888)


class FrameType(Enum):
    HANDSHAKE = 'h'
    START = 's'
    DATA = 'd'
    ACK = 'a'


class PDU:
    def __init__(self, data=None):
        self.data: bytes = data
        self.size = MESSAGE_SIZE
        self.checksum = b''
        if self.data is not None:
            self.size = len(self.data) - CHECKSUM_SIZE
            self.message = self.data[:self.size]
            self.checksum = self.data[self.size:]

    @staticmethod
    def ACK(seqno: int) -> 'PDU':
        message = f"{seqno}|ACK"
        return PDU().pack(message, FrameType.ACK)

    @staticmethod
    def SYNACK() -> 'PDU':
        return PDU().pack("SYN|ACK", FrameType.ACK)

    @staticmethod
    def Start_ACK(filename: str) -> 'PDU':
        message = f"{filename}|ACK"
        return PDU().pack(message, FrameType.ACK)

    def calc_checksum(self, data) -> bytes:
        # TODO how to define number of bytes for checksum????
        return zlib.adler32(data).to_bytes(CHECKSUM_SIZE, byteorder='big')

    def pack(self, data: str | bytes, frame_type: FrameType) -> 'PDU':
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
                    header = b'a|'
            return header + data

        data = data.encode('utf-8') if type(data) is str else data
        data = make_header()

        self.checksum = self.calc_checksum(data)
        self.data = data + self.checksum
        return self

    def check(self) -> bool:
        cal_checksum = self.calc_checksum(self.message)
        return cal_checksum == self.checksum

    def unpack(self) -> bytes:
        if not self.check():
            raise InvalidPDUException("Checksum mismatch!")
        message = self.data[:self.size]
        return message


# TODO close socket
class Socket:
    def __init__(self, home_address: tuple[str, int], address: tuple[str, int]):
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

    def close(self):
        self.sock.close()


class Host:
    def __init__(self, address, ws=STANDARD_WS):
        self.address = address
        self.ws = ws
        self.connections: {str: {}} = {}
        self.hosts_ws: {str: int} = {}
        self.files = {}
        self.receive_thread = None

    def add_connection(self, host_address: tuple[str, int]):
        if host_address in self.connections.keys():
            print("Already connected")
            raise ExistingConnectionException

        self.connections[host_address] = {
            "socket": Socket(self.address, host_address),
            "GetACK": Event(),
            "start_time": [0 for _ in range(self.ws)]
        }
        self.receive_thread = Thread(target=self.receive, args=(host_address,))
        self.receive_thread.start()

    def handle_message(self, message: bytes, sender_address: tuple[str, int]):
        # TODO ADD SOME DATA TO WS
        # handshake: header|WS
        # start:     header|filename|file_size
        # data:      header|seqno|data
        # ack:       header|data|ACK
        header = FrameType(message[:HEADER_SIZE].decode())
        match header:
            case FrameType.ACK:
                _, data, ack = message.split(b'|', 2)
                data = data.decode('utf-8')
                try:
                    data = int(data)
                    if data == self.files[sender_address]['seqno']:
                        # Stop timer -> activate the event "Get ACK"
                        self.connections[sender_address]['GetACK'].set()
                except ValueError:
                    self.connections[sender_address]['GetACK'].set()
            case FrameType.HANDSHAKE:
                _, ws = message.split(b'|', 1)
                self.hosts_ws[sender_address] = int(ws.decode())
                self.connections[sender_address]['socket'].send(PDU.SYNACK())
            case FrameType.START:
                _, filename, file_size = message.split(b'|', 2)
                filename, file_size = map(lambda x: x.decode(), (filename, file_size))
                file_path = os.path.join(os.getcwd(), filename)

                if os.path.exists(file_path):
                    os.remove(file_path)

                self.files[sender_address] = {
                    "file": open(file_path, 'wb'),
                    "size": int(file_size),
                    "seqno": 0,
                    "rec_size": 0
                }
                self.connections[sender_address]['socket'].send(PDU.Start_ACK(filename))

            case FrameType.DATA:
                _, seqno, data = message.split(b'|', 2)
                seqno = int(seqno.decode())

                if seqno != self.files[sender_address]["seqno"]:
                    return

                self.files[sender_address]["seqno"] += 1
                self.files[sender_address]["file"].write(data)
                self.files[sender_address]["rec_size"] += len(data)

                self.connections[sender_address]['socket'].send(PDU.ACK(seqno))

                if self.files[sender_address]["rec_size"] == self.files[sender_address]["size"]:
                    self.files[sender_address]["file"].close()
                    self.files.pop(sender_address)

    def receive(self, host_address: tuple[str, int]):
        # TODO check -> May be not true
        # We have a thread per connection, so timeouts_number is local variable
        timeouts_number = 0
        while True:
            try:
                data = self.connections[host_address]["socket"].recframe()
                self.handle_message(data, host_address)
                timeouts_number = 0
            except timeout:
                if timeouts_number == TIMEOUT_NUMBER:
                    #  TODO Break connection
                    print("Break the connection!")
                timeouts_number += 1

    def await_ack(self, address: tuple[str, int], passed_time: int = 0):
        if self.connections[address]['GetACK'].wait(TIMER_ACK - passed_time):
            print("ACK!")
            self.connections[address]['GetACK'].clear()
        else:
            print("NACK!")
            raise Timeout

    def send_sync(self, ws: int, address: tuple[str, int]):
        if address not in self.connections.keys():
            raise NoConnectionException
        frame = PDU().pack(str(ws), FrameType.HANDSHAKE)
        self.connections[address]['socket'].send(frame)
        self.await_ack(address)

    def send_file(self, file: str, address: tuple[str, int]):
        if address not in self.connections.keys():
            raise NoConnectionException

        file_size = os.path.getsize(file)
        start_frame = PDU().pack(f"{file}_send|{file_size}", FrameType.START)
        data_chunks = [start_frame]
        with open(file, "rb") as f:
            for i in range((file_size + MESSAGE_SIZE - 1) // MESSAGE_SIZE):
                data = f.read(MESSAGE_SIZE)
                seqno = i % self.ws
                data_chunks.append(f"{seqno}|{data}")

        wait_frames_ack = 0
        i = 0
        while i <= len(data_chunks):
            try:
                if wait_frames_ack == self.ws:
                    seqno = (i + 1) % self.ws
                    passed_time = round(time.time()) - self.connections[address]['start_time'][seqno]
                    self.await_ack(address, passed_time)
                    wait_frames_ack -= 1

                data_frame = PDU().pack(data_chunks[i], FrameType.DATA)
                self.connections[address]['socket'].send(data_frame)
                self.connections[address]['start_time'][i % self.ws] = round(time.time())
                wait_frames_ack += 1
                i += 1
            except Timeout:
                i -= self.ws
                wait_frames_ack = 0
                print("Timeout frame!")


# TODO handle ACK
class Connector:
    def __init__(self):
        pass

    def create_connection(self, host1: Host, host2: Host):
        host1.add_connection(host2.address)
        host2.add_connection(host1.address)
        self.handshake()

    def handshake(self):
        attempts = 0
        while True:
            try:
                print("SYNC1")
                host1.send_sync(host1.ws, host2.address)
                print("SYNC2")
                host2.send_sync(host2.ws, host1.address)
                print("Successful Handshake!")
                break
            except Timeout as e:
                print(e)
                attempts += 1
                if attempts == CONNECTION_ATTEMPTS:
                    raise LimitSentAttemptsException


# TODO STAYING ALIVE


# TODO User Input
# TODO make different paths for different hosts/change file name after receiving
# TODO make Keyboard stop
if __name__ == '__main__':
    host1 = Host(HOST1_ADDR, ws=4)
    host2 = Host(HOST2_ADDR, ws=5)

    connector = Connector()

    try:
        connector.create_connection(host1, host2)
    except LimitSentAttemptsException:
        print("No Connection established")
    except ExistingConnectionException as e:
        print(e)

    # host1.send_file("pic.img", host2.address)

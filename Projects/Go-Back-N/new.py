import os
import time
import zlib
from enum import Enum
from threading import Thread, Event
from socket import socket, AF_INET, SOCK_DGRAM, timeout

from exceptions import NoConnectionException, \
	LimitSentAttemptsException, Timeout, ExistingConnectionException

HEADER_SIZE = 1
CHECKSUM_SIZE = 4

MESSAGE_SIZE = 4000
MAX_FRAME_SIZE = MESSAGE_SIZE + 20

TIMER_ACK = 5
TIMER = 5


class FrameType(Enum):
	HANDSHAKE = 'h'
	START = 's'
	DATA = 'd'
	ACK = 'a'
	SYN = 'y'


class PDU:
	def __init__(self, data=None):
		self.data: bytes = data
		self.size = MESSAGE_SIZE
		self.checksum = b''
		if self.data is not None:
			self.message = self.data[HEADER_SIZE: -CHECKSUM_SIZE]
			self.header = self.data[:HEADER_SIZE]
			self.checksum = self.data[-CHECKSUM_SIZE:]

	@staticmethod
	def ACK(seqno: int) -> 'PDU':
		message = f"{seqno}"
		return PDU().pack(message, FrameType.ACK)

	@staticmethod
	def SYNACK(ws: int = None) -> 'PDU':
		message = "SYN"
		if ws is not None:
			message += f"|{ws}"
		return PDU().pack(message, FrameType.SYN)

	@staticmethod
	def Start_ACK(filename: str) -> 'PDU':
		message = f"{filename}"
		return PDU().pack(message, FrameType.ACK)

	def calc_checksum(self, data) -> bytes:
		return zlib.adler32(data).to_bytes(CHECKSUM_SIZE, byteorder='big')

	def pack(self, data, frame_type: FrameType) -> 'PDU':
		def make_header():
			match frame_type:
				case FrameType.HANDSHAKE:
					header = FrameType.HANDSHAKE.value.encode()
				case FrameType.START:
					header = FrameType.START.value.encode()
				case FrameType.DATA:
					header = FrameType.DATA.value.encode()
				case FrameType.ACK:
					header = FrameType.ACK.value.encode()
				case FrameType.SYN:
					header = FrameType.SYN.value.encode()
				case _:
					raise ValueError(f"Unknown frame type: {frame_type}")
			return header + data

		data = data.encode('utf-8') if type(data) is str else data
		data = make_header()

		self.checksum = self.calc_checksum(data)
		self.data = data + self.checksum
		return self

	def check(self) -> bool:
		cal_checksum = self.calc_checksum(self.header + self.message)
		return cal_checksum == self.checksum

	def unpack(self) -> tuple[FrameType, bytes]:
		return FrameType(self.header.decode()), self.message


class Receiver:
	def __init__(self, host):
		self.sock = socket(AF_INET, SOCK_DGRAM)
		self.host = host
		self.sock.bind(host.address)

		self.next_seq = {}

	def receive(self):
		while True:
			try:
				data, addr = self.sock.recvfrom(MAX_FRAME_SIZE)
				frame = PDU(data)
				self.host.handle_frame(frame, addr)
			# return frame, addr
			except timeout or ExistingConnectionException:
				...


class Socket:
	def __init__(self, address: tuple[str, int]):
		self.sock = socket(AF_INET, SOCK_DGRAM)
		self.receiver_address = address
		self.sock.settimeout(TIMER)

	def send(self, frame: PDU):
		self.sock.sendto(frame.data, self.receiver_address)

	def close(self):
		self.sock.close()


class Connection:
	def __init__(self, rec_addr: tuple[str, int], rec_ws=0):
		self.addr = rec_addr
		self.file_info = {}
		self.ws = rec_ws  # TODO do we need this?
		self.ack_event = Event()
		self.start_time = [0 for _ in range(self.ws)]
		self.socket = Socket(self.addr)


class Sender:
	def __init__(self, ws: int):
		self.ws = ws

	def await_ack(self, timer: Event, passed_time: int = 0):
		if timer.wait(TIMER_ACK - passed_time):
			timer.clear()
		else:
			raise Timeout

	def send_packages(self, packages: list[PDU], connection: Connection):
		wait_frames_ack = 0
		i = 0
		while i < len(packages):
			try:
				if wait_frames_ack == self.ws:
					seqno = i % self.ws
					passed_time = round(time.time()) - connection.start_time[seqno]
					self.await_ack(connection.ack_event, passed_time)
					print(f"ACK {seqno}")
					wait_frames_ack -= 1

				connection.socket.send(packages[i])
				print(f"Send {i}({i % self.ws}) frame out of {len(packages)}")
				# Start timer! Save the moment of send time
				connection.start_time[i % self.ws] = round(time.time())
				wait_frames_ack += 1
				i += 1
			except Timeout:
				i -= self.ws
				wait_frames_ack = 0
				print("Timeout frame!")
		print("Done!")

	def send_frame(self, frame: PDU, connection: Connection):
		connection.socket.send(frame)



class Host:
	def __init__(self, address, ws=5):
		self.address = address
		self.ws = ws

		self.connections: {tuple: Connection} = {}

		self.sender = Sender(self.ws)

		self.receiver = Receiver(self)
		self.receive_thread = Thread(target=self.receiver.receive)
		self.receive_thread.start()

	def add_connection(self, receiver_addr: tuple[str, int]):
		if receiver_addr in self.connections.keys():
			print("Already connected")
			raise ExistingConnectionException
		self.connections[receiver_addr] = Connection(receiver_addr)

	def send_file(self, file, addr):
		# Prepare file frames for sending
		file_size = os.path.getsize(file)
		start_frame = PDU().pack(f"send_{file}|{file_size}", FrameType.START)
		data_chunks = [start_frame]
		with open(file, "rb") as f:
			for i in range((file_size + MESSAGE_SIZE - 1) // MESSAGE_SIZE):
				data = f.read(MESSAGE_SIZE)
				seqno = i % self.ws
				frame_data = PDU().pack(f"{seqno}|".encode() + data, FrameType.DATA)
				data_chunks.append(frame_data)

		self.sender.send_packages(data_chunks, self.connections[addr])

	def make_handshake(self, addr):
		# Send ws
		syn = PDU().pack(str(self.ws), FrameType.HANDSHAKE)
		self.sender.send_frame(syn, self.connections[addr])

		# Wait for SYN WS
		#TODO try catch Timeout
		self.await_ack(self.connections[addr].ack_event)

		# Send SYN ACK
		frame = PDU().SYNACK()
		self.sender.send_frame(frame)


if __name__ == "__main__":
	host1 = Host(("localhost", 8888))

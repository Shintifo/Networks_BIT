import configparser
import os
import random
import time
import zlib
from enum import Enum
from threading import Thread, Event
from socket import socket, AF_INET, SOCK_DGRAM, timeout

from exceptions import InvalidPDUException, NACKException, NoConnectionException, \
	LimitSentAttemptsException, Timeout, ExistingConnectionException

# NOTE: I consider that between 2 hosts we can create only 1 connection
#       and host1 cannot send 2 files in parallel to host2

TIMER_ACK = 2
TIMER = 2

CONNECTION_ATTEMPTS = 5
TIMEOUT_NUMBER = 5

HEADER_SIZE = 1
CHECKSUM_SIZE = 4

MESSAGE_SIZE = 4096
MAX_FRAME_SIZE = MESSAGE_SIZE + 20

STANDARD_WS = 3


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
		return PDU().pack(message, FrameType.ACK)

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
				case _:
					raise ValueError(f"Unknown frame type: {frame_type}")
			self.header = header
			return header + data

		data = data.encode('utf-8') if type(data) is str else data
		data = make_header()

		self.checksum = self.calc_checksum(data)
		self.data = data + self.checksum
		self.header = self.data
		return self

	def check(self) -> bool:
		cal_checksum = self.calc_checksum(self.header + self.message)
		return cal_checksum == self.checksum

	def unpack(self) -> tuple[FrameType, bytes]:
		return FrameType(self.header.decode()), self.message

	def error(self):
		index_to_change = random.randint(0, len(self.data) - 1)
		new_byte_value = random.randint(0, 255)
		self.data = self.data[:index_to_change] + bytes([new_byte_value]) + self.data[index_to_change + 1:]


class Socket:
	def __init__(self, home_address: tuple[str, int], address: tuple[str, int]):
		self.sock = socket(AF_INET, SOCK_DGRAM)
		self.sock.settimeout(TIMER)
		self.sock.bind(home_address)
		self.receiver_address = address

	def recframe(self) -> PDU:
		try:
			data, addr = self.sock.recvfrom(MAX_FRAME_SIZE)
			frame = PDU(data)
			return frame
		except InvalidPDUException as e:
			print(e)
			raise NACKException()

	def send(self, frame: PDU):
		self.sock.sendto(frame.data, self.receiver_address)

	def close(self):
		self.sock.close()


class Host:
	def __init__(self, address, ws, lost_rate, init_seqno, error_rate):
		self.lost_rate = lost_rate
		self.InitSeqNo = init_seqno
		self.error_rate = error_rate

		self.address = address
		self.ws = ws
		self.connections: {tuple: {}} = {}
		self.files = {}
		self.receive_thread = None
		self.next_seqno: {tuple: int} = {}

	def add_connection(self, host_address: tuple[str, int]):
		if host_address in self.connections.keys():
			print("Already connected")
			raise ExistingConnectionException

		self.connections[host_address] = {
			"ws": 0,
			"socket": Socket(self.address, host_address),
			"GetACK": Event(),
			"start_time": [0 for _ in range(self.ws)]
		}
		self.receive_thread = Thread(target=self.receive, args=(host_address,))
		self.receive_thread.daemon = True
		self.receive_thread.start()

	def handle_message(self, frame: PDU, sender_address: tuple[str, int]):
		# handshake: WS
		# start:     filename|file_size
		# data:      seqno|data
		# ack:       data ("SYN", "SYN|{ws}", filename, seqno)
		# print(f"rec {frame.unpack()}")
		if not frame.check():
			print(f"Mismatch checksum!")
			return

		header, message = frame.unpack()
		match header:
			case FrameType.ACK:
				data = message.decode('utf-8')
				try:
					data = int(data)
					# It's Data ACK with seqno
					if data == self.next_seqno[sender_address]:
						self.next_seqno[sender_address] += 1
						self.next_seqno[sender_address] %= self.ws
						while True:
							if self.connections[sender_address]['GetACK'].is_set():
								continue
							break
						self.connections[sender_address]['GetACK'].set()
				# else:
				# 	print(f"Expected:{self.next_seqno[sender_address]}, got {data}")
				except ValueError:
					# It's start (filename) and SYN
					self.connections[sender_address]['GetACK'].set()

			case FrameType.HANDSHAKE:
				# It is new connection we have to create the connection
				# self.add_connection(sender_address)

				self.connections[sender_address]['ws'] = int(message.decode())
				self.send_frame(PDU.SYNACK(), sender_address)

			case FrameType.START:
				filename, file_size = message.split(b'|', 1)
				filename, file_size = map(lambda x: x.decode(), (filename, file_size))
				file_path = os.path.join(os.getcwd(), filename)

				if os.path.exists(file_path):
					os.remove(file_path)

				self.files[sender_address] = {
					"file": open(file_path, 'wb'),
					"size": int(file_size),
					"seqno": 1,
					"rec_size": 0
				}
				self.send_frame(PDU.ACK(0), sender_address)

			case FrameType.DATA:
				seqno, data = message.split(b'|', 1)
				seqno = int(seqno.decode())

				# If seqno is smth random:
				# 	- bigger than expected
				# 	- invalid (<0)
				# We consider that we didn't receive anything
				if seqno > self.files[sender_address]["seqno"] or seqno < 0:
					print(seqno)
					return

				# We record the data if only we got frame with expected seqno
				# Otherwise, it's a duplicate

				if seqno == self.files[sender_address]["seqno"]:
					self.files[sender_address]["seqno"] += 1
					self.files[sender_address]["seqno"] %= self.connections[sender_address]['ws']
					self.files[sender_address]["file"].write(data)
					self.files[sender_address]["rec_size"] += len(data)
					print(f"{self.files[sender_address]["rec_size"]} out of {self.files[sender_address]["size"]}")
					if self.files[sender_address]["rec_size"] == self.files[sender_address]["size"]:
						print("Close file")
						self.files[sender_address]["file"].close()
						self.files.pop(sender_address)
				# print("Send ACK")
				self.send_frame(PDU.ACK(seqno), sender_address)

	def receive(self, host_address: tuple[str, int]):
		timeouts_number = 0  # If there is no messages for a long time -> Break connection
		while True:
			try:
				data = self.connections[host_address]["socket"].recframe()
				self.handle_message(data, host_address)
				timeouts_number = 0
			except timeout:
				if timeouts_number == TIMEOUT_NUMBER:
					print("Break the connection!")
					exit()
				timeouts_number += 1
			except NACKException:
				timeouts_number = 0

	def await_ack(self, address: tuple[str, int], passed_time: int = 0):
		if self.connections[address]['GetACK'].wait(TIMER_ACK - passed_time):
			self.connections[address]['GetACK'].clear()
		else:
			raise Timeout

	def send_sync(self, address: tuple[str, int]):
		if address not in self.connections.keys():
			raise NoConnectionException
		frame = PDU().pack(str(self.ws), FrameType.HANDSHAKE)
		self.send_frame(frame, address)
		self.await_ack(address)

	def send_frame(self, frame: PDU, addr):
		lost = random.randint(1, self.lost_rate)
		error = random.randint(1, self.error_rate)
		if lost == 1:
			lost = random.randint(1, self.lost_rate)
			if lost == 1:
				print("Lost!")
				return
		# if error == 1:
		# 	print(frame.data[:-CHECKSUM_SIZE])
		# 	print(f"Error!")
		# 	frame.error()
		self.connections[addr]['socket'].send(frame)

	def send_file(self, file: str, address: tuple[str, int]):
		if address not in self.connections.keys():
			raise NoConnectionException

		file_size = os.path.getsize(file)
		start_frame = PDU().pack(f"send_{file}|{file_size}", FrameType.START)
		data_chunks = [start_frame]
		with open(file, "rb") as f:
			for i in range((file_size + MESSAGE_SIZE - 1) // MESSAGE_SIZE):
				data = f.read(MESSAGE_SIZE)
				seqno = (i + 1) % self.ws
				frame_data = PDU().pack(f"{seqno}|".encode() + data, FrameType.DATA)
				data_chunks.append(frame_data)

		wait_frames_ack = 0
		i = 0
		self.next_seqno[address] = 0
		while i <= len(data_chunks):
			try:
				if i != len(data_chunks):
					print(f"Send {i}({i % self.ws}) frame out of {len(data_chunks) - 1}")
					self.send_frame(data_chunks[i], address)
					self.connections[address]['start_time'][i % self.ws] = round(time.time())
					wait_frames_ack += 1
					i += 1
				if wait_frames_ack == self.ws or i == len(data_chunks):
					seqno = i % self.ws
					passed_time = round(time.time()) - self.connections[address]['start_time'][seqno]
					self.await_ack(address, passed_time)
					# print(f"Get ACK {seqno}")
					wait_frames_ack -= 1
					if wait_frames_ack == 0 and i == len(data_chunks):
						break

			except Timeout:
				i -= self.ws
				wait_frames_ack = 0
				print(f"Timeout frame!")

		print("Done!")


class Connector:
	def __init__(self):
		pass

	def create_connection(self, host1: Host, host2: Host):
		host1.add_connection(host2.address)
		host2.add_connection(host1.address)
		self.handshake(host1, host2)

	def handshake(self, host1, host2):
		attempts = 0
		while True:
			try:
				print("SYNC1")
				host1.send_sync(host2.address)
				print("SYNC2")
				host2.send_sync(host1.address)
				print("Successful Handshake!")
				break
			except Timeout as e:
				print(e)
				attempts += 1
				if attempts == CONNECTION_ATTEMPTS:
					raise LimitSentAttemptsException


def config_parse(config_file):
	global TIMER
	global MESSAGE_SIZE
	config = configparser.ConfigParser()
	config.read(config_file)

	UDPPort = int(config.get('UDPSettings', 'UDPPort'))
	DataSize = int(config.get('PDUSettings', 'DataSize'))
	SWSize = int(config.get('WindowSettings', 'SWSize'))
	Timeout = int(config.get('TimeoutSettings', 'Timeout'))

	LostRate = int(config.get('PDUSettings', 'LostRate'))
	InitSeqNo = int(config.get('SequenceSettings', 'InitSeqNo'))
	ErrorRate = int(config.get('PDUSettings', 'ErrorRate'))

	MESSAGE_SIZE = int(DataSize)
	host = Host(("localhost", UDPPort), SWSize, LostRate, InitSeqNo, ErrorRate)
	TIMER = int(Timeout) // 1000
	return host


def create_host(a):
	return config_parse(a)


def host1_script(host):
	T = "test.txt"
	P = "pic.jpg"
	V = "vid.MP4"
	host.send_file(P, ("localhost", 8803))
	time.sleep(0.1)


def host2_script(host):
	host.send_file("pic.jpg", ("localhost", 3088))


if __name__ == '__main__':
	host1 = create_host("config_H1.ini")
	host2 = create_host("config_H2.ini")

	connector = Connector()
	connector.create_connection(host1, host2)

	thread1 = Thread(target=host1_script, args=(host1,))
	thread2 = Thread(target=host2_script, args=(host2,))
	thread1.start()
	thread2.start()

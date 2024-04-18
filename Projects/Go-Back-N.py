import os
import queue
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
TIMER_ACK = 1111
TIMER = 11111

CONNECTION_ATTEMPTS = 5
TIMEOUT_NUMBER = 5

HEADER_SIZE = 1
CHECKSUM_SIZE = 4

MESSAGE_SIZE = 4000
MAX_FRAME_SIZE = MESSAGE_SIZE + 20

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
			self.message = self.data[HEADER_SIZE: -CHECKSUM_SIZE]
			self.header = self.data[:HEADER_SIZE]
			self.checksum = self.data[-CHECKSUM_SIZE:]

	@staticmethod
	def ACK(seqno: int) -> 'PDU':
		message = f"{seqno}"
		return PDU().pack(message, FrameType.ACK)

	@staticmethod
	def SYNACK() -> 'PDU':
		return PDU().pack("SYN", FrameType.ACK)

	@staticmethod
	def Start_ACK(filename: str) -> 'PDU':
		message = f"{filename}"
		return PDU().pack(message, FrameType.ACK)

	def calc_checksum(self, data) -> bytes:
		# TODO how to define number of bytes for checksum????
		return zlib.adler32(data).to_bytes(CHECKSUM_SIZE, byteorder='big')

	def pack(self, data, frame_type: FrameType) -> 'PDU':
		def make_header():
			header = b''
			match frame_type:
				case FrameType.HANDSHAKE:
					header = b'h'
				case FrameType.START:
					header = b's'
				case FrameType.DATA:
					header = b'd'
				case FrameType.ACK:
					header = b'a'
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


# TODO close socket
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
	def __init__(self, address, ws=STANDARD_WS):
		self.address = address
		self.ws = ws
		self.connections: {tuple: {}} = {}
		self.hosts_ws: {tuple: int} = {}
		self.files = {}
		self.receive_thread = None
		self.next_seqno_ack: {tuple: int} = {}

	def add_connection(self, host_address: tuple[str, int]):
		if host_address in self.connections.keys():
			print("Already connected")
			raise ExistingConnectionException

		self.connections[host_address] = {
			"socket": Socket(self.address, host_address),
			"GetACK": [Event() for _ in range(self.ws)],
			"start_time": [0 for _ in range(self.ws)]
		}
		self.receive_thread = Thread(target=self.receive, args=(host_address,))
		self.receive_thread.start()

	def handle_message(self, frame: PDU, sender_address: tuple[str, int]):
		# handshake: WS
		# start:     filename|file_size
		# data:      seqno|data
		# ack:       data ("SYN", filename, seqno)
		if not frame.check():
			print("Mismatch checksum!")
			return

		# TODO handle split error
		header, message = frame.unpack()
		match header:
			case FrameType.ACK:
				data = message.decode('utf-8')
				try:
					data = int(data)
					# It's Data ACK with seqno
					if data == self.next_seqno_ack[sender_address]:
						self.next_seqno_ack[sender_address] += 1
						self.next_seqno_ack[sender_address] %= self.ws
						self.connections[sender_address]['GetACK'][data].set()
				except ValueError:
					# It's handshake ("SYN") or start (filename)
					self.connections[sender_address]['GetACK'][0].set()

			case FrameType.HANDSHAKE:
				self.hosts_ws[sender_address] = int(message.decode())
				self.connections[sender_address]['socket'].send(PDU.SYNACK())

			case FrameType.START:
				filename, file_size = message.split(b'|', 1)
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
				seqno, data = message.split(b'|', 1)
				seqno = int(seqno.decode())

				# If seqno is smth random:
				# 	- bigger than expected
				# 	- invalid (<0)
				# We consider that we didn't receive anything
				if seqno > self.files[sender_address]["seqno"] or seqno < 0:
					return

				# We record the data if only we got frame with expected seqno
				# Otherwise, it's a duplicate
				if seqno == self.files[sender_address]["seqno"]:
					self.files[sender_address]["seqno"] += 1
					self.files[sender_address]["seqno"] %= self.hosts_ws[sender_address]
					self.files[sender_address]["file"].write(data)
					self.files[sender_address]["rec_size"] += len(data)

					if self.files[sender_address]["rec_size"] == self.files[sender_address]["size"]:
						print("Close file")
						self.files[sender_address]["file"].close()
						self.files.pop(sender_address)

				self.connections[sender_address]['socket'].send(PDU.ACK(seqno))

	def receive(self, host_address: tuple[str, int]):
		# TODO check -> May be not true
		# We have a thread per connection, so timeouts_number is local variable
		timeouts_number = 0  # If there is no messages for a long time -> Break connection
		while True:
			try:
				data = self.connections[host_address]["socket"].recframe()
				self.handle_message(data, host_address)
				timeouts_number = 0
			except timeout:
				if timeouts_number == TIMEOUT_NUMBER:
					#  TODO Break connection
					print("Break the connection!")
					exit()
				timeouts_number += 1
			except NACKException:
				timeouts_number = 0

	def await_ack(self, address: tuple[str, int], seqno: int, passed_time: int = 0):
		if self.connections[address]['GetACK'][seqno].wait(TIMER_ACK - passed_time):
			self.connections[address]['GetACK'][seqno].clear()
		else:
			raise Timeout

	def send_sync(self, ws: int, address: tuple[str, int]):
		if address not in self.connections.keys():
			raise NoConnectionException
		frame = PDU().pack(str(ws), FrameType.HANDSHAKE)
		self.connections[address]['socket'].send(frame)
		self.await_ack(address, 0)

	def send_file(self, file: str, address: tuple[str, int]):
		if address not in self.connections.keys():
			raise NoConnectionException

		file_size = os.path.getsize(file)
		start_frame = PDU().pack(f"send_{file}|{file_size}", FrameType.START)
		data_chunks = [start_frame]
		with open(file, "rb") as f:
			for i in range((file_size + MESSAGE_SIZE - 1) // MESSAGE_SIZE):
				data = f.read(MESSAGE_SIZE)
				seqno = i % self.ws
				frame_data = PDU().pack(f"{seqno}|".encode() + data, FrameType.DATA)
				data_chunks.append(frame_data)

		i = 0
		# Required for receiving ACKs
		self.next_seqno_ack[address] = 0

		error_queue = queue.Queue()
		threads_arr = [Thread() for _ in range(self.ws)]

		while i < len(data_chunks):
			# Check the number of active threads.
			# If we have less than WS -> we have an error, or received ACK
			# We receive an ACK if only it is expected ACK
			if sum(t.is_alive() for t in threads_arr) == self.ws:
				continue
			# Considering timer > RTT, so we can get ACK2 before timer for ACK1 ends up.
			# It means if we got ACK2 before getting ACK1, the timeout for ACK2 raise

			# Check queue for error raised in thread
			if not error_queue.empty():
				error_seqno = error_queue.get_nowait()

				# We consider that we can obtain error (timeout or NACk) only in last frame in window
				# Example:
				# 0 | 1 2 3 | 4
				# We got an error at frame 3 and got ACKs for 1 and 2 frames
				# It happened simultaneously, so we check for error before trying to send next frames
				# In order to not resend frames 1 and 2, we need firstly move the window
				if i % self.ws > error_seqno:
					surplus = self.ws - abs(i % self.ws - error_seqno)
				else:
					surplus = abs(i % self.ws - error_seqno)
				i += surplus

				# TODO Stop all threads (race condition)
				# We will just wait till the end of all threads (too long)
				for t in threads_arr:
					t.join() if t.isAlive() else ...
				error_queue = queue.Queue()
				i = max(0, i - self.ws)
				print("Timeout frame!")
				continue

			# Send frame
			self.connections[address]['socket'].send(data_chunks[i])
			print(f"Send {i}({i % self.ws}) frame out of {len(data_chunks)}")
			i += 1
			# Start timer
			threads_arr[i % self.ws] = Thread(
				target=self.thread_wait_ack,
				args=(i % self.ws, address, error_queue)
			)
			threads_arr[i % self.ws].start()
		print("Done!")

	def thread_wait_ack(self, seqno, address, error_queue):
		try:
			self.await_ack(address, seqno)
			# print(f"ACK {address}")
		except Timeout:
			error_queue.put(seqno)


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
# TODO make Keyboard stop
if __name__ == '__main__':
	host1 = Host(HOST1_ADDR, ws=4)
	host2 = Host(HOST2_ADDR, ws=5)

	connector = Connector()

	try:
		connector.create_connection(host1, host2)
	except LimitSentAttemptsException:
		print("No Connection established")
		exit()
	except ExistingConnectionException as e:
		print(e)

	start = time.time()
	host1.send_file("vid.MP4", host2.address)
	print(time.time() - start)

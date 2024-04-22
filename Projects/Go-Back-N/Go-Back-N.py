import configparser
import copy
import logging
import os
import random
import time
import zlib
from enum import Enum
from threading import Thread, Event
from socket import socket, AF_INET, SOCK_DGRAM, timeout


# NOTE: I consider that between 2 hosts we can create only 1 connection
#       and host1 cannot send 2 files in parallel to host2

# I Consider that all host use the same data size

class NACKException(Exception):
	def __init__(self, message="NACK"):
		super().__init__(message)


class Timeout(Exception):
	def __init__(self, message="timeout!"):
		super().__init__(message)


class NoConnectionException(Exception):
	def __init__(self, message="No existing such connection"):
		super().__init__(message)


class ExistingConnectionException(Exception):
	def __init__(self, message="Connection with this server already exists"):
		super().__init__(message)


TIMEOUT_NUMBER = 50
HEADER_SIZE = 1
CHECKSUM_SIZE = 4
INFO_DATA = 20


class PDUSendStatus(Enum):
	NEW = 'NEW'
	TO = 'Timeout Retransmission'
	RT = "Retransmission"


class PDURecStatus(Enum):
	OK = 'Correct'
	DataErr = 'Data Error'
	NoErr = 'Sequential Number Error '


class FrameType(Enum):
	HANDSHAKE = 'h'
	START = 's'
	DATA = 'd'
	ACK = 'a'


class PDU:
	def __init__(self, data=None):
		self.data: bytes = data
		self.status = PDUSendStatus.NEW
		self.type = None
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

	def get_seqno(self) -> str:
		if self.type == FrameType.DATA:
			return self.message.split(b'|', maxsplit=1)[0].decode()

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
			self.type = FrameType(header.decode())
			self.header = header

		self.message = data.encode('utf-8') if type(data) is str else data
		make_header()
		self.checksum = self.calc_checksum(self.header + self.message)
		self.data = self.header + self.message + self.checksum
		return self

	def check(self) -> bool:
		cal_checksum = self.calc_checksum(self.header + self.message)
		return cal_checksum == self.checksum

	def unpack(self) -> tuple[FrameType, bytes]:
		return FrameType(self.header.decode()), self.message

	def noise(self):
		index_to_change = random.randint(0, len(self.data) - 1)
		new_byte_value = random.randint(0, 255)
		self.data = self.data[:index_to_change] + bytes([new_byte_value]) + self.data[index_to_change + 1:]


class Socket:
	def __init__(self, home_address: tuple[str, int], address: tuple[str, int],
				 framesize: int, timer: float):
		self.sock = socket(AF_INET, SOCK_DGRAM)
		self.sock.settimeout(timer)
		self.sock.bind(home_address)
		self.receiver_address = address
		self.frame_size = framesize

	def recframe(self) -> PDU:
		data, addr = self.sock.recvfrom(self.frame_size + INFO_DATA)
		frame = PDU(data)
		return frame

	def send(self, frame: PDU):
		self.sock.sendto(frame.data, self.receiver_address)

	def close(self):
		self.sock.close()


class Host:
	def __init__(self, address, ws, data_size, init_seqno, timer, lost_rate, error_rate, folder):
		self.InitSeqNo = init_seqno
		self.lost_rate = lost_rate
		self.error_rate = error_rate
		self.frame_size = data_size
		self.timer = timer
		self.host_folder = folder

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
			"socket": Socket(self.address, host_address, self.frame_size, self.timer),
			"GetACK": Event(),
			"NACK": Event(),
			"start_time": [0 for _ in range(self.ws + 1)]
		}
		self.receive_thread = Thread(target=self.receive, args=(host_address,))
		self.receive_thread.daemon = True
		self.receive_thread.start()

	def handle_message(self, frame: PDU, sender_address: tuple[str, int]):
		# handshake: WS
		# start:     filename|file_size
		# data:      seqno|data
		# ack:       data ("SYN", "SYN|{ws}", seqno)
		if not frame.check():
			print(f"Mismatch checksum!")
			if frame.type in [FrameType.START, FrameType.DATA]:
				if frame.type == FrameType.START:
					exp_seqno = 0
					filename = frame.message.split(b'|', maxsplit=1)[0].decode()
					if "rec_" + filename not in log_files:
						print("Couldn't define file name and write in corresponding log file")
						return
				else:
					exp_seqno = self.files[sender_address]["seqno"]
					filename = self.files[sender_address]["filename"]
				rec_log("rec_" + filename, exp_seqno, frame.get_seqno(), PDURecStatus.DataErr.name)
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
						self.next_seqno[sender_address] %= (self.ws + 1)
						while True:
							if not self.connections[sender_address]['GetACK'].is_set():
								self.connections[sender_address]['GetACK'].set()
								break
				except ValueError:  # It's SYN ACK
					self.connections[sender_address]['GetACK'].set()

			case FrameType.HANDSHAKE:
				self.connections[sender_address]['ws'] = int(message.decode())
				self.send_frame(PDU.SYNACK(), sender_address)

			case FrameType.START:
				filename, file_size = message.split(b'|', 1)
				filename, file_size = map(lambda x: x.decode(), (filename, file_size))
				file_path = os.path.join(os.getcwd(), self.host_folder, filename)

				if os.path.exists(file_path):
					os.remove(file_path)

				self.files[sender_address] = {
					"filename": filename.split(".")[0],
					"file": open(file_path, 'wb'),
					"size": int(file_size),
					"seqno": 1,
					"rec_size": 0
				}
				log_name = "rec_" + filename.split(".")[0]
				create_new_log(self.host_folder, log_name, False)
				rec_log(log_name, 0, 0, PDURecStatus.OK.name)
				self.send_frame(PDU.ACK(0), sender_address)

			case FrameType.DATA:
				seqno, data = message.split(b'|', 1)
				seqno = int(seqno.decode())
				# We record the data if only we got frame with expected seqno
				# Otherwise, it's a duplicate

				if sender_address in self.files.keys() and seqno == self.files[sender_address]["seqno"]:
					rec_log("rec_" + self.files[sender_address]["filename"], self.files[sender_address]["seqno"],
							seqno, PDURecStatus.OK.name)
					self.files[sender_address]["seqno"] += 1
					self.files[sender_address]["seqno"] %= self.connections[sender_address]['ws']
					self.files[sender_address]["file"].write(data)
					self.files[sender_address]["rec_size"] += len(data)
					if self.files[sender_address]["rec_size"] == self.files[sender_address]["size"]:
						print(f"Close file")
						self.files[sender_address]["file"].close()
						self.files.pop(sender_address)
				else:
					rec_log("rec_" + self.files[sender_address]["filename"], self.files[sender_address]["seqno"],
							seqno, PDURecStatus.NoErr.name)
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

	def await_ack(self, address: tuple[str, int], passed_time: int = 0):
		if (self.connections[address]['GetACK'].wait(self.timer - passed_time) or
				self.connections[address]['NACK'].wait(self.timer - passed_time)):
			if self.connections[address]['GetACK'].is_set():
				self.connections[address]['GetACK'].clear()
			else:
				self.connections[address]['NACK'].clear()
				raise NACKException
		else:
			raise Timeout

	def send_sync(self, address: tuple[str, int]):
		if address not in self.connections.keys():
			raise NoConnectionException
		frame = PDU().pack(str(self.ws + 1), FrameType.HANDSHAKE)
		self.send_frame(frame, address)
		self.await_ack(address)

	def send_frame(self, frame: PDU, addr, filename=None, frameNo=None):
		if frame.type in [FrameType.START, FrameType.DATA]:
			if frame.type == FrameType.START:
				create_new_log(self.host_folder, "send_" + filename, True)
				seqno = 0
			else:
				seqno = frame.get_seqno()
			send_log("send_" + filename, seqno, frame.status.name, frameNo)

		lost = random.randint(0, self.lost_rate)
		error = random.randint(0, self.error_rate)
		if lost == 0:
			# print(f"Lost!")
			return
		if error == 0:
			error_frame = copy.deepcopy(frame)
			error_frame.noise()
			self.connections[addr]['socket'].send(error_frame)
		# print(f"Error!")
		else:
			self.connections[addr]['socket'].send(frame)

	def send_file(self, file: str, address: tuple[str, int]):
		# Check existing connection
		if address not in self.connections.keys():
			raise NoConnectionException

		# Divide file by frames
		file_size = os.path.getsize(file)
		start_frame = PDU().pack(f"{file}|{file_size}", FrameType.START)
		data_chunks = [start_frame]

		with open(file, "rb") as f:
			for i in range((file_size + self.frame_size - 1) // self.frame_size):
				data = f.read(self.frame_size)
				seqno = (i + 1) % (self.ws + 1)
				frame_data = PDU().pack(f"{seqno}|".encode() + data, FrameType.DATA)
				data_chunks.append(frame_data)

		# Go-Back-N
		wait_frames_ack = 0
		i = 0
		self.next_seqno[address] = 0
		step_back = self.ws
		while i <= len(data_chunks):
			try:
				if i != len(data_chunks):
					# print(f"Send {i}({i % (self.ws + 1)}) frame out of {len(data_chunks) - 1}")
					self.send_frame(data_chunks[i], address, file.split(".")[0], i)
					# Note the time of sending frame
					self.connections[address]['start_time'][i % (self.ws + 1)] = round(time.time())
					wait_frames_ack += 1
					i += 1
				if wait_frames_ack == self.ws or i == len(data_chunks):
					seqno = (i - 1) % (self.ws + 1)  # Seqno of the oldest frame we wait for
					passed_time = round(time.time()) - self.connections[address]['start_time'][seqno]
					self.await_ack(address, passed_time)
					# print(f"Get ACK {seqno}")
					wait_frames_ack -= 1
					if i == len(data_chunks):
						step_back -= 1
					if wait_frames_ack == 0 and i == len(data_chunks):
						break

			except Timeout:
				data_chunks[i - step_back].status = PDUSendStatus.TO
				for k in range(1, step_back):
					data_chunks[i - k].status = PDUSendStatus.RT
				i -= step_back
				wait_frames_ack = 0
				print(f"Timeout frame!")
			except NACKException:
				for k in range(1, step_back + 1):
					data_chunks[i - k].status = PDUSendStatus.RT
				i -= step_back
				wait_frames_ack = 0
				print(f"NACK!")
		print("Done!")


class Connector:
	def __init__(self):
		pass

	def create_connection(self, host1: Host, host2: Host):
		host1.add_connection(host2.address)
		host2.add_connection(host1.address)
		self.handshake(host1, host2)

	def handshake(self, host1, host2):
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


def create_host(config_file):
	config = configparser.ConfigParser()
	config.read(config_file)

	hostNo = config.getint("UDPSettings", "HostNo")
	os.makedirs(f"Host{hostNo}", exist_ok=True)
	folder = f"Host{hostNo}"

	UDPPort = config.getint('UDPSettings', 'UDPPort')
	SWSize = config.getint('WindowSettings', 'SWSize')
	Timeout = config.getint('TimeoutSettings', 'Timeout') / 1000
	LostRate = config.getint('PDUSettings', 'LostRate')
	ErrorRate = config.getint('PDUSettings', 'ErrorRate')
	InitSeqNo = config.getint('SequenceSettings', 'InitSeqNo')
	DataSize = config.getint('PDUSettings', 'DataSize')

	host = Host(("localhost", UDPPort), SWSize, DataSize, InitSeqNo, Timeout, LostRate, ErrorRate, folder)
	return host


def host2_script(host):
	host.send_file("vid.MP4", ("localhost", 3088))


def host1_script(host):
	host.send_file("pic.jpg", ("localhost", 9999))


def send_log(filename, seqno, status, ackno):
	log_data = {
		'seqno': seqno,
		'status': status,
		'ackno': ackno,
	}
	log_files[filename].info('', extra=log_data)


def rec_log(filename, exp_seqno, rec_seqno, status):
	log_data = {
		'exp_seqno': exp_seqno,
		'rec_seqno': rec_seqno,
		'status': status,
	}
	log_files[filename].info('', extra=log_data)


def create_new_log(folder, filename, is_send):
	path = os.path.join(folder, filename)
	if os.path.exists(f'{path}.log'):
		os.remove(f'{path}.log')

	log_files[filename] = logging.getLogger(path)
	log_files[filename].setLevel(logging.INFO)

	file_handler = logging.FileHandler(f'{path}.log')
	file_handler.setLevel(logging.INFO)
	if is_send:
		log_format = logging.Formatter('%(asctime)s, pdu_to_send=%(seqno)s, status=%(status)s, ackedNo=%(ackno)s')
	else:
		log_format = logging.Formatter('%(asctime)s, pdu_exp=%(exp_seqno)s, pdu_recv=%(rec_seqno)s, status=%(status)s')

	file_handler.setFormatter(log_format)

	log_files[filename].addHandler(file_handler)


log_files = {}

if __name__ == '__main__':
	host1 = create_host("config_H1.ini")
	host2 = create_host("config_H2.ini")

	connector = Connector()
	connector.create_connection(host1, host2)

	thread1 = Thread(target=host1_script, args=(host1,))
	thread2 = Thread(target=host2_script, args=(host2,))
	thread2.start()
	thread1.start()

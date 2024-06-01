import datetime
from socket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR
from threading import Thread
import os
import subprocess
from urllib.parse import unquote
import logging

MAX_CONNECTIONS = 10
PORT = 8888

BASE_PATH = os.path.join(os.getcwd(), "webroot")
LOG_PATH = os.path.join(BASE_PATH, "log/requests.log")


class RequestType:
	GET = "GET"
	POST = "POST"
	HEAD = "HEAD"


class Server:
	def __init__(self):
		self.sock = socket(AF_INET, SOCK_STREAM)
		self.sock.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
		self.sock.bind(('localhost', PORT))
		self.threads: [Thread] = []

		self.create_database()

	def __del__(self):
		self.sock.close()

	def create_database(self):
		if not os.path.exists(os.path.join(os.getcwd(), "students.db")):
			subprocess.run(["python", os.path.join(os.getcwd(), "CreateDB.py")], capture_output=True, text=True)

	def start(self):
		self.sock.listen()
		while True:
			client_sock, addr = self.sock.accept()
			if len(self.threads) == MAX_CONNECTIONS:
				oldest_thread = self.threads.pop(0)
				oldest_thread.join()

			thread = Thread(target=self.handler, args=(client_sock, addr,))
			thread.start()
			self.threads.append(thread)

	@staticmethod
	def parse_request(request):
		req_lines = request.split('\r\n')
		req_dict = {}
		first_line = req_lines[0].split(' ')
		req_dict['Method'] = first_line[0]
		req_dict['Path'] = first_line[1]
		req_dict['HTTP_Version'] = first_line[2]

		for idx, line in enumerate(req_lines[1:]):
			if line == '':
				break
			key, value = line.split(': ', 1)
			req_dict[key] = value

		if req_lines[-1] != '':
			params = []
			for line in req_lines[-1].split('&'):
				_, value = line.split('=', 1)
				if value is None or value == '':
					continue
				params.append(unquote(value))
			req_dict["Parameters"] = params

		return req_dict

	def open_not_found(self, client_sock):
		self.send_header(client_sock, 404)
		path = os.path.join(BASE_PATH, '404.html')
		with open(path, "rb") as file:
			client_sock.sendfile(file, 0)

	def send_header(self, client_sock, header_code):
		response_header = ''
		match header_code:
			case 200:
				response_header = (f'HTTP/1.1 404 Not Found\r\n'
								   f'Content-Type: text/html\r\n\r\n')
			case 404:
				response_header = (f'HTTP/1.1 404 Not Found\r\n'
								   f'Content-Type: text/html\r\n\r\n')

		client_sock.send(response_header.encode())

	def get_log(self):
		path = LOG_PATH

		logger = logging.getLogger(path)
		logger.setLevel(logging.INFO)

		file_handler = logging.FileHandler(f'{path}')
		file_handler.setLevel(logging.INFO)

		logger.addHandler(file_handler)
		return logger

	def handler(self, client_sock, addr):
		data = client_sock.recv(1024).decode('utf-8')
		# print(data.encode())
		if data == '':
			return

		data = self.parse_request(data)
		log_info = f"{addr[0]} -- {data['User-Agent']} -- {addr[1]} -- {datetime.UTC} -- {data['Method']} -- {data['Path']}"

		if 'cgi-bin' in data['Path']:
			log_info = self.cgi(data=data, client_sock=client_sock, log_info=log_info)
		else:
			log_info = self.static_web(data=data, client_sock=client_sock, log_info=log_info)
		client_sock.close()

		if "Referer" in data.keys():
			log_info += f" -- {data['Referer']}"

		logger = self.get_log()
		logger.info(log_info)

	def static_web(self, data, client_sock, log_info):
		file_path = BASE_PATH + "/" + data["Path"]
		match data['Method']:
			case RequestType.GET:
				if not os.path.exists(file_path):
					self.open_not_found(client_sock)
					log_info += f" -- 404"
					return log_info

				if data['Path'] == '/':
					file_path = os.path.join(BASE_PATH, "index.html")

				self.send_header(client_sock, 200)
				log_info += f"-- 200"
				log_info += f"-- {os.path.getsize(file_path)}"
				with open(file_path, "rb") as file:
					client_sock.sendfile(file, 0)
			case RequestType.HEAD:
				if not os.path.exists(file_path):
					self.send_header(client_sock, 404)
					log_info += f" -- 404"
				else:
					self.send_header(client_sock, 200)
					log_info += f" -- 200"
		return log_info

	def cgi(self, data, client_sock, log_info):
		file_path = BASE_PATH + data["Path"]
		match data["Method"]:
			case RequestType.GET:
				if not os.path.exists(file_path):
					self.open_not_found(client_sock)
					log_info += f" -- 404"
					return log_info
				result = subprocess.run(["python", file_path], capture_output=True, text=False).stdout
				log_info += f" -- 200"
				log_info += f" -- {os.path.getsize(file_path)}"
				self.send_header(client_sock, 200)
				client_sock.send(result)

			case RequestType.HEAD:
				if not os.path.exists(file_path):
					self.send_header(client_sock, 404)
					log_info += f" -- 404"
				else:
					self.send_header(client_sock, 200)
					log_info += f" -- 200"

			case RequestType.POST:
				if not os.path.exists(file_path):
					self.open_not_found(client_sock)
					log_info += f" -- 404"
					return log_info

				ext = data['Path'].split(".")[-1]
				match ext:
					case 'py':
						command = "python"
					case 'sh':
						command = "bash"
				result = subprocess.run(
					[command, file_path] + data['Parameters'],
					capture_output=True, text=False).stdout
				self.send_header(client_sock, 200)

				log_info += f" -- 200"
				log_info += f" -- {os.path.getsize(file_path)}"
				if b'.html' in result:
					path = os.path.join(BASE_PATH, result.decode())
					with open(path, "rb") as file:
						client_sock.sendfile(file)
				else:
					client_sock.send(result)
		return log_info


if __name__ == "__main__":
	try:
		server = Server()
		server.start()
	except KeyboardInterrupt:
		print("Shutting down...")

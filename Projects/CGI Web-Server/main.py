from socket import socket, AF_INET, SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR
from threading import Thread
import os
import subprocess
from urllib.parse import unquote

MAX_CONNECTIONS = 10
PORT = 8888

BASE_PATH = os.path.join(os.getcwd(), "webroot")

# TODO QST
# TODO Log files


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

		# self.create_database()

	def __del__(self):
		self.sock.close()

	def create_database(self):
		subprocess.run([os.path.join(os.getcwd(), "CreateDB.py")], check=True)

	def start(self):
		self.sock.listen()
		while True:
			client_sock, addr = self.sock.accept()
			if len(self.threads) == MAX_CONNECTIONS:
				oldest_thread = self.threads.pop(0)
				oldest_thread.join()

			thread = Thread(target=self.handler, args=(client_sock,))
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
			req_dict["Parameters"] = req_lines[-1]

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

	def handler(self, client_sock):
		data = client_sock.recv(1024)
		print(data)
		data = data.decode('utf-8')
		data = self.parse_request(data)
		if 'cgi-bin' in data['Path']:
			self.cgi(data=data, client_sock=client_sock)
		else:
			self.static_web(data=data, client_sock=client_sock)

	def static_web(self, data, client_sock):
		file_path = BASE_PATH + "/" + data["Path"]
		match data['Method']:
			case RequestType.GET:
				if not os.path.exists(file_path):
					self.open_not_found(client_sock)
					client_sock.close()
					return

				if data['Path'] == '/':
					file_path = os.path.join(BASE_PATH, "index.html")

				self.send_header(client_sock, 200)

				with open(file_path, "rb") as file:
					client_sock.sendfile(file, 0)
			case RequestType.HEAD:
				if not os.path.exists(file_path):
					self.send_header(client_sock, 404)
				else:
					self.send_header(client_sock, 200)

		client_sock.close()

	def cgi(self, data, client_sock):
		file_path = BASE_PATH + data["Path"]
		match data["Method"]:
			case RequestType.GET:
				if not os.path.exists(file_path):
					self.open_not_found(client_sock)
					client_sock.close()
					return
				script = data['Path'][9:]
				if script == 'number.py':
					result = subprocess.run(["python", file_path], capture_output=True, text=False).stdout
				elif script == 'submit_questionnaire.py':
					result = subprocess.run(["python", file_path], capture_output=True, text=False).stdout
				else:
					result = "Incorrect script".encode()
				self.send_header(client_sock, 200)
				client_sock.send(result)

			case RequestType.HEAD:
				if not os.path.exists(file_path):
					self.send_header(client_sock, 404)
				else:
					self.send_header(client_sock, 200)

			case RequestType.POST:
				script = data['Path'][9:]
				if script == 'calculator.sh':
					parameters = {}
					for line in data['Parameters'].split('&'):
						key, value = line.split('=', 1)
						parameters[key] = value
					result = subprocess.run(
						[
							'bash',
							file_path,
							parameters['num1'],
							parameters['num2'],
							unquote(parameters['operator'])
						],
						capture_output=True, text=False).stdout
				elif script == 'submit_questionnaire.py':
					result = subprocess.run(["python", file_path], capture_output=True, text=False).stdout
				else:
					result = "Incorrect script".encode()
				self.send_header(client_sock, 200)
				client_sock.send(result)

		client_sock.close()


if __name__ == "__main__":
	try:
		server = Server()
		server.start()
	except KeyboardInterrupt:
		print("That's it")

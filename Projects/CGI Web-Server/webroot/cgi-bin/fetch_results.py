import sqlite3
import argparse

if __name__ == '__main__':
	parser = argparse.ArgumentParser()
	parser.add_argument("id", type=int, help="Student ID")
	args = parser.parse_args()

	if args.id is None:
		print("all")
		query = "SELECT * FROM students"
	else:
		query = f"SELECT * FROM students WHERE student_id = {args.id}"

	conn = sqlite3.connect('students.db')
	cursor = conn.cursor()

	cursor.execute(query)
	conn.commit()
	cursor.close()
	conn.close()
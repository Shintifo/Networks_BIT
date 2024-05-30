import os
import sqlite3
import argparse
import subprocess


def argument_parser():
	parser = argparse.ArgumentParser()
	parser.add_argument("id", type=int, help="Student ID")
	parser.add_argument("name", type=str, help="Name")
	parser.add_argument("gender", type=str, help="Gender")
	parser.add_argument("major", type=str, help="Major")
	parser.add_argument("sport", type=str, help="Sport")

	args = parser.parse_args()
	vals = []
	for key, value in args.__dict__.items():
		if isinstance(value, str):
			value = value.replace("+", " ")
		vals.append(value)
	return vals


def connect():
	if not os.path.exists(os.path.join(os.getcwd(), "students.db")):
		res = subprocess.run(["python", os.path.join(os.getcwd(), "CreateDB.py")],
							 capture_output=True, text=True).stdout

	mydb = sqlite3.connect("students.db")
	mycursor = mydb.cursor()
	return mydb, mycursor


if __name__ == "__main__":
	mydb, mycursor = connect()

	vals = argument_parser()
	insert_query = (
		"INSERT INTO results (STUDENT_ID, NAME, GENDER, MAJOR, SPORT) "
		"VALUES (?, ?, ?, ?, ?)"
	)

	mycursor.execute(insert_query, vals)
	mydb.commit()
	mycursor.close()
	mydb.close()

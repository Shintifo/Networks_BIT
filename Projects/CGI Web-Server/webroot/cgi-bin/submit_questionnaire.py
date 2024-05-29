import mysql.connector
import argparse


def argument_parser():
	parser = argparse.ArgumentParser()
	parser.add_argument("id", type=int, help="Student ID")
	parser.add_argument("name", type=str, help="Name")
	parser.add_argument("Gender", type=str, help="Gender")
	parser.add_argument("Major", type=str, help="Major")
	parser.add_argument("Sport", type=str, help="Sport")
	args = parser.parse_args()

	return (args.id, args.name, args.Gender, args.Major, args.Sport)


mydb = mysql.connector.connect(host="localhost", user="root", database="QST")
mycursor = mydb.cursor()

insert_query = (
	"INSERT INTO results ("
	"STUDENT_ID, NAME, GENDER, MAJOR, SPORT)"
	"VALUES (%s, %s, %s, %s, %s)"
)

vals = argument_parser()

mycursor.execute(insert_query, vals)
mycursor.close()
mydb.commit()
mydb.close()

import sqlite3

create_table = (
	"CREATE TABLE IF NOT EXISTS results("
	"STUDENT_ID INT NOT NULL PRIMARY KEY,"
	"NAME VARCHAR(255) NOT NULL,"
	"GENDER VARCHAR(255),"
	"MAJOR VARCHAR(255),"
	"SPORT VARCHAR(255)"
	")"
)
try:
	connector = sqlite3.connect("students.db")
	cursor = connector.cursor()

	cursor.execute(create_table)

	cursor.close()
	connector.close()
except Exception as e:
	print(e)


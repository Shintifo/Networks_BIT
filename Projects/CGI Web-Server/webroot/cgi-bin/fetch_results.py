import os
import sqlite3
import argparse


def construct_query():
	parser = argparse.ArgumentParser()
	parser.add_argument('-o', "--id", type=str, help="Student ID")
	args = parser.parse_args()
	if args.id is None:
		query = "SELECT * FROM results"
	else:
		query = f"SELECT * FROM results WHERE student_id = {int(args.id)}"
	return query


def fetch(query):
	conn = sqlite3.connect('students.db')
	cursor = conn.cursor()

	cursor.execute(query)
	students = cursor.fetchall()

	cursor.close()
	conn.close()
	return students


def fill_template(students):

	with open("webroot/fetch_template.html", "r") as template_file:
		content = template_file.read()

	results = ""

	for student in students:
		results += (f"\t<tr>\n"
					f"\t\t\t\t\t<td>{student[0]}</td>\n")
		results += f"\t\t\t\t\t<td>{student[1]}</td>\n"
		results += f"\t\t\t\t\t<td>{student[2]}</td>\n"
		results += f"\t\t\t\t\t<td>{student[3]}</td>\n"
		results += (f"\t\t\t\t\t<td>{student[4]}</td>\n"
					f"\t\t\t\t</tr>\n\t\t\t")

	s = content.find("<tbody>")
	e = content.find("</tbody>", s)

	new_data = content[:e] + results + content[e:]
	with open("webroot/fetch_results.html", "w") as result_file:
		result_file.write(new_data)

	path = os.path.join(os.getcwd(), "webroot/fetch_results.html")
	print(path, end='')


if __name__ == '__main__':
	query = construct_query()
	students = fetch(query)
	fill_template(students)

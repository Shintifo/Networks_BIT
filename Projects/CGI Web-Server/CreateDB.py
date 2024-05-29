# import mysql.connector
#
# mydb = mysql.connector.connect(host="localhost", user="user", passwd="password")
# print(mydb)
#
# exit()
# mycursor = mydb.cursor()
#
# mycursor.execute("CREATE DATABASE IF NOT EXISTS QST")
#
# create_table = (
# 	"CREATE TABLE IF NOT EXISTS results("
# 	"STUDENT_ID INT NOT NULL PRIMARY KEY"
# 	"NAME VARCHAR(255) NOT NULL,"
# 	"GENDER VARCHAR(255),"
# 	"MAJOR VARCHAR(255),"
# 	"SPORT VARCHAR(255)"
# 	")"
# )
#
# mycursor.execute(create_table)
# mycursor.close()
# mydb.close()


import mysql.connector

dataBase = mysql.connector.connect(
	host="localhost",
	user="1",
	passwd="pswrd"
)

print(dataBase)

# Disconnecting from the server
# dataBase.close()

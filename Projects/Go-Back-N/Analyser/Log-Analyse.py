import pandas as pd
import matplotlib.pyplot as plt
import configparser


def read_log_file(file_path):
	with open(file_path, 'r') as file:
		data = file.read().split('\n')

	# Split each line into components
	data = [x.split(',') for x in data if x]

	# Split the first component (timestamp) into date and time
	data = [[x[0].split(' ')[0], x[0].split(' ')[1], x[2].strip(" pdu_to_send"), x[3].strip(" status="),
			 x[4].strip(" ackedNo")] for x in data]

	# Create a DataFrame from the data
	df = pd.DataFrame(data, columns=['date', 'time', 'pdu_to_send', 'status', 'ackedNo'])

	# Convert date and time to a single datetime column
	df['timestamp'] = pd.to_datetime(df['date'] + ' ' + df['time'])

	# Drop the date and time columns
	df = df.drop(['date', 'time'], axis=1)

	return df


# Function to read parameters from config.ini file
def read_config_file(file_path):
	config = configparser.ConfigParser()
	config.read(file_path)
	params['ws'].append(config.getint('WindowSettings', 'SWSize'))
	params['frame_size'].append(config.getint('PDUSettings', 'DataSize'))
	return params


# Function to analyze data and calculate statistics
def analyze_data(df):
	errors_losses = df['status'].value_counts()['TO'] + df['status'].value_counts()['RT']
	total_time = df['timestamp'].max() - df['timestamp'].min()
	return total_time, errors_losses


# Function to plot data
def plot_data(params, x_label, y_label, title):
	plt.plot(params[x_label], params[y_label])
	plt.xlabel(x_label)
	plt.ylabel(y_label)
	plt.title(title)
	plt.show()


def sep_run(log, config):
	# Read log file
	df = read_log_file(log)
	read_config_file(config)
	total_time, errors_losses = analyze_data(df)

	# Add error+loss rates and total time to params
	params['errors_losses'].append(errors_losses)
	params['total_time'].append(total_time.total_seconds())


params = {
	"ws": [],
	"frame_size": [],
	'errors_losses': [],
	'total_time': [],
}

for i in range(1,6):
	sep_run(f"{i}.log", f"{i}.ini")

# Plot data
plot_data(params, 'ws', 'errors_losses', 'Window Size vs Errors+Losses')
plot_data(params, 'ws', 'total_time', 'Window Size vs Total Time')
# plot_data(params, 'frame_size', 'errors_losses', 'Frame Size vs Errors+Losses')
# plot_data(params, 'frame_size', 'total_time', 'Frame Size vs Total Time')

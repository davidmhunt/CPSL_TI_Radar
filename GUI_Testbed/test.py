from math import pi
import matplotlib.pyplot as plt
import numpy as np
import time

# generating random data values
x = np.linspace(1, 1000, 5000)
y = np.random.randint(1, 1000, 5000)

# enable interactive mode
plt.ion()

# creating subplot and figure
fig = plt.figure()
ax = fig.add_subplot(111)
line1, = ax.plot(x, y)

# setting labels
plt.xlabel("X-axis")
plt.ylabel("Y-axis")
plt.title("Updating plot...")

# looping
for _ in range(50):

	# updating the value of x and y
	line1.set_xdata(x*_)
	line1.set_ydata(y)

	# re-drawing the figure
	fig.canvas.draw()
	
	# to flush the GUI events
	fig.canvas.flush_events()
	time.sleep(0.1)

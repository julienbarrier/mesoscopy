
import matplotlib
matplotlib.use('Qt5Agg')
import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = fig.add_subplot(111)
        super(MplCanvas, self).__init__(fig)

class LivePlottingSubscriber:
    def __init__(self, canvas, x_dim, y_dim=1):
        self.canvas = canvas
        self.is_2d = y_dim > 1
        self.x_dim = x_dim
        self.y_dim = y_dim
        if self.is_2d:
            self.x_data = np.zeros((x_dim, y_dim))
            self.y_data = np.zeros((x_dim, y_dim))
            self.z_data = np.zeros((x_dim, y_dim))
            self.i = 0
            self.j = 0
        else:
            self.x_data = []
            self.y_data = []

    def __call__(self, result_list):
        if self.is_2d:
            if self.i < self.x_dim and self.j < self.y_dim:
                self.x_data[self.i, self.j] = result_list[0]
                self.y_data[self.i, self.j] = result_list[1]
                self.z_data[self.i, self.j] = result_list[2]
                
                self.j += 1
                if self.j == self.y_dim:
                    self.j = 0
                    self.i += 1
                
                if self.j == 0: # Update plot every line
                    self.update_plot()
        else:
            if len(result_list) >= 2:
                self.x_data.append(result_list[0])
                self.y_data.append(result_list[1])
                self.update_plot()

    def update_plot(self):
        self.canvas.axes.cla()
        if self.is_2d:
            self.canvas.axes.pcolormesh(self.x_data, self.y_data, self.z_data, shading='auto')
        else:
            self.canvas.axes.plot(self.x_data, self.y_data, '.-')
        self.canvas.draw()

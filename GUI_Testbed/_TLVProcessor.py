import numpy as np
import matplotlib.pyplot as plt
from matplotlib.collections import PathCollection
from matplotlib.figure import Figure
from matplotlib.axes import Axes
import matplotlib
from PyQt5 import QtCore,QtWidgets
import time

class DetectedPointsProcessor:
    def __init__(self,plotting_enabled=True):
        
        matplotlib.use("QtAgg")
        plt.ion()
        
        self.detected_objects:np.array(type=np.float32)

        #storing radar performance variables
        self.radar_performance:dict = None

        #initialize figures and axis for the plots
        self.plotting_enabled = plotting_enabled

        #figure and axis for the plots
        self.fig:Figure = None
        self.axs:Axes = None

        #plot for the xy detections
        self.scat_xy:PathCollection = None
        self.scat_yz:PathCollection = None

    def load_config(self,radar_performance:dict):

        #load the new radar performance values
        self.radar_performance = radar_performance

        #initialize the plots
        self._init_plots()
    
    def _init_plots(self):
        if self.plotting_enabled:
            
            #determine max range
            max_range = self.radar_performance["range"]["range_max"]

            #if there was already a figure open, close it so that the new one can be created
            if self.fig != None:
                plt.close(self.fig)

            self.fig,self.axs = plt.subplots(2)

            #initialize the full plot
            self.fig.suptitle("Detected Objects")

            #initialize the xy subplot
            self.scat_xy = self.axs[0].scatter([],[])
            self.axs[0].set_title("X,Y detections")
            self.axs[0].set_xlabel("X (meters)")
            self.axs[0].set_ylabel("Y (meters)")
            self.axs[0].set_xlim((-max_range,max_range))
            self.axs[0].set_ylim((0,max_range))

            #initialize the yz subplot
            self.scat_yz = self.axs[1].scatter([],[])
            self.axs[1].set_title("Y,Z detections")
            self.axs[1].set_xlabel("Y (meters)")
            self.axs[1].set_ylabel("Z (meters)")
            self.axs[1].set_xlim((0,max_range))
            self.axs[1].set_ylim((-max_range,max_range))

            self.fig.canvas.draw()
            self.fig.canvas.flush_events()
            time.sleep(1e-3)

    def process_new_data(self,data:bytearray):
        descriptor = np.frombuffer(data[8:12],dtype=np.uint16)
        num_objects = descriptor[0]
        XYZQ_format = descriptor[1]
        XYZQ_conversion = np.power(2,XYZQ_format)
        
        #start forming the detected objects array
        objects_struct = np.frombuffer(data[12:],dtype=np.int16)
        #reshape so that each row corresponds to a specific object
        objects_struct = objects_struct.reshape([-1,6])

        range_idxs = objects_struct[:,0].astype(np.uint16)
        ranges = np.float32(range_idxs * self.radar_performance["range"]["range_idx_to_m"])

        vel_idxs = objects_struct[:,1]
        vels = np.float32(vel_idxs * self.radar_performance["velocity"]["vel_idx_to_m_per_s"])

        peak_vals = (objects_struct[:,2]/XYZQ_conversion).astype(np.float32)

        XYZ_coordinates = (objects_struct[:,3:]/XYZQ_conversion).astype(np.float32)

        self.detected_objects = np.concatenate((XYZ_coordinates,vels[:,np.newaxis],ranges[:,np.newaxis],peak_vals[:,np.newaxis]),axis=1)

        if self.plotting_enabled:
            self._update_plots()
        
        return
    
    def _update_plots(self):
        x = self.detected_objects[:,0]
        y = self.detected_objects[:,1]
        z = self.detected_objects[:,2]
        self.scat_xy.set_offsets(np.c_[x,y])
        self.scat_yz.set_offsets(np.c_[y,z])
        
        #update the plots
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()
        time.sleep(1e-3)
        
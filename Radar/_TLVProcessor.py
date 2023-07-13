import numpy as np
import matplotlib.pyplot as plt
from matplotlib.collections import PathCollection
from matplotlib.figure import Figure
from matplotlib.axes import Axes
import matplotlib
from PyQt5 import QtCore,QtWidgets
import time
from collections import OrderedDict
import imageio
import io
from multiprocessing.connection import Listener

class DetectedPointsProcessor:
    def __init__(self,plotting_enabled=True, save_as_gif = False):
        
        matplotlib.use("QtAgg")
        plt.ion()
        
        self.detected_objects:np.array(type=np.float32)

        #storing radar performance variables
        self.radar_performance:dict = None
        self.radar_config = OrderedDict()

        #initialize figures and axis for the plots
        self.plotting_enabled = plotting_enabled

        #saving plots to a file (as a .gif)
        self.save_as_gif_enabled = save_as_gif
        self.gif_file_name = "DetectedPoints.gif"
        self.image_frames = None
        self.frame_duration = None

        #figure and axis for the plots
        self.fig:Figure = None
        self.axs:Axes = None

        #plot for the xy detections
        self.scat_xy:PathCollection = None
        self.scat_yz:PathCollection = None

        #TLV client connection to send data to an external process
        self._conn_listener_enabled = False
        self._listener = None
        self._conn_listener = None

    def load_config(self,radar_performance:dict, radar_config:OrderedDict):

        #load the new radar performance values
        self.radar_performance = radar_performance
        self.radar_config = radar_config

        #initialize the plots
        self._init_plots()

        #init saving to a gif
        self._init_save_to_gif()


# Sending data to an external process
    def init_conn_client(self,address,authkey):
        """initialize the client connection to send data to an external process

        Args:
            address (tuple): address in the form ('localhost',address)
            authkey (binary string): authentication key in the form b'authkey' 
        """

        #setup a new connection with a listener at the address
        #blocks until the connection is established
        self._listener = Listener(address,authkey=authkey)
        self._conn_listener = self._listener.accept()
        self._conn_listener_enabled = True

# Handling plots and saving plots to a .gif
    def _init_plots(self):
        if self.plotting_enabled:
            
            #determine max range
            max_range = self.radar_performance["range"]["range_max"]

            #if there was already a figure open, close it so that the new one can be created
            if self.fig != None:
                plt.close(self.fig)

            self.fig,self.axs = plt.subplots(2)
            plt.subplots_adjust(hspace=0.6)

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
    
    def _init_save_to_gif(self):
        if self.plotting_enabled and self.save_as_gif_enabled:
            #initialize the image frames
            self.image_frames = []
            self.frame_duration = float(self.radar_config["frameCfg"]["periodicity"]) * 1e-3

    def save_gif_to_file(self):
        if self.plotting_enabled and self.save_as_gif_enabled:
            imageio.mimsave(self.gif_file_name,self.image_frames,duration=self.frame_duration)

    def _update_plots(self):
        x = self.detected_objects[:,0]
        y = self.detected_objects[:,1]
        z = self.detected_objects[:,2]
        self.scat_xy.set_offsets(np.c_[x,y])
        self.scat_yz.set_offsets(np.c_[y,z])
        
        #update the plots
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()

        if self.save_as_gif_enabled:
            buf = io.BytesIO()
            self.fig.savefig(buf,format='png',dpi=300)
            buf.seek(0)
            self.image_frames.append(imageio.imread(buf))

#processing data
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
        
        if self._conn_listener_enabled:
            self._conn_listener.send(self.detected_objects)
        
        return
        
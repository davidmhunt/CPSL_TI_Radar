from multiprocessing.connection import Connection
from multiprocessing import connection,AuthenticationError

import numpy as np
import matplotlib.pyplot as plt
import matplotlib
#import cv2
from multiprocessing.connection import Listener
import threading

from CPSL_TI_Radar.Processors._Processor import _Processor

class DCA1000Processor(_Processor):

    LVDS_lanes = 4

    #plotting parameters
    font_size_title = 14
    font_size_axis_labels = 12
    font_size_color_bar = 10

    def __init__(self,
                 conn_parent:Connection,
                 conn_processor_data:Connection,
                 settings_file_path='config_Radar.json'):
        """Initialization process for DCA1000 Processor class

        Args:
            conn_parent (connection): connection to the parent process (RADAR)
            conn_processor_data (Connection): connection to pass data between Processors and Streamers.
            settings_file_path (str, optional): path to the RADAR config file. Defaults to 'config_RADAR.json'.
        """
        
        super().__init__(conn_parent=conn_parent,
                         settings_file_path=settings_file_path,
                         conn_processor_data=conn_processor_data)
        
        self.current_packet = bytearray()
        
        #key radar parameters
        #TODO: enable these at a later time
        self.max_range_bin = 64 #enable this a bit better
        self.num_chirps_to_save = 0 #set from config
        self.num_angle_bins = 64
        self.rng_az_power_range_dB = [70,105]
        self.rng_dop_poer_range_dB = [70,140]


        #key radar parameters
        self.rx_channels = 0
        self.num_az_antennas = 0
        self.virtual_antennas_enabled = 0
        
        #number of chirps per loop and chirp loops per frame
        self.chirps_per_loop = 0
        self.chirp_loops_per_frame = 0
        self.total_chirps_per_frame = 0
        self.samples_per_chirp = 0
        
        #compute range bins
        self.range_bins = None

        #velocity bins
        self.num_vel_bins = 0
        self.velocity_bins = None

        #compute angular parameters
        self.phase_shifts = None
        self.angle_bins = None

        #mesh grid coordinates for plotting
        self.thetas = None
        self.rhos = None
        self.x_s = None
        self.y_s = None

        #plotting
        self.plotting_enabled = self._settings["Processor"]["enable_plotting"]
        self.fig = None
        self.axs = None
        self.rng_az_cart = None #range az cartesian image
        self.rng_az_sph = None #range az spherical image

        #listeners
        self._listeners_enabled = False
        self._listener_ADCDataCube_enabled = False
        self._listener_ADCDataCube = None
        self._conn_ADCDataCube = None
        self._conn_ADCDataCube_enabled = False

        self._listener_NormRngAzResp_enabled = False
        self._listener_NormRngAzResp = None
        self._conn_NormRngAzResp = None
        self._conn_NormRngAzResp_enabled = None

        self._listener_NormRngDopResp_enabled = False
        self._listener_NormRngDopResp = None
        self._conn_NormRngDopResp = None
        self._conn_NormRngDopResp_enabled = None

        self._listener_RadCloudModel_enabled = False
        self._listener_RadCloudModel = None
        self._conn_RadCloudModel = None
        self._conn_RadCloudModel_enabled = None

        self._listener_PointCloud_enabled = False
        self._listener_PointCloud = None
        self._conn_PointCloud = None
        self._conn_PointCloud_enabled = None

        #video
        self.zoom = 5

        self._conn_send_init_status(self.init_success)
        self.run()

        return
    
    def close(self):
        #if self.plotting_enabled:
        #    cv2.destroyAllWindows()
        pass

    def _load_new_config(self, config_info: dict):

        #call the parent class method to save the new radar config and performance
        super()._load_new_config(config_info)

        #key radar parameters
        self.rx_channels = self.radar_performance["angle"]["num_rx_antennas"]
        self.num_az_antennas = self.radar_performance["angle"]["num_az_antennas"]
        self.virtual_antennas_enabled = self.radar_performance["angle"]["virtual_anetnnas_enabled"]
        
        #number of chirps per loop and chirp loops per frame
        chirp_start_profile_idx = int(self.radar_config["frameCfg"]["startIndex"])
        chirp_end_profile_idx = int(self.radar_config["frameCfg"]["endIndex"])
        self.chirps_per_loop = chirp_end_profile_idx - chirp_start_profile_idx + 1
        self.chirp_loops_per_frame = int(self.radar_config["frameCfg"]["loops"])
        #TODO: currently hardcoded to the number of chirps in a frame although this can be adjusted
        self.num_chirps_to_save = self.chirp_loops_per_frame
        self.total_chirps_per_frame = self.chirp_loops_per_frame * self.chirps_per_loop
        self.samples_per_chirp = int(self.radar_config["profileCfg"]["adcSamples"])
        
        #compute range bins
        range_res = self.radar_performance["range"]["range_res"]
        self.range_bins = np.arange(0,self.samples_per_chirp) * range_res

        #compute doppler bins
        vel_res = self.radar_performance["velocity"]["vel_res"]
        vel_max = self.radar_performance["velocity"]["vel_max"]
        self.num_vel_bins = int(self.radar_performance["velocity"]["num_doppler_bins"])
        self.velocity_bins = np.arange(-1 * vel_max,vel_max,vel_res)


        #compute angular parameters
        self.phase_shifts = np.arange(np.pi,-np.pi  - 2 * np.pi /(self.num_angle_bins - 1),-2 * np.pi / (self.num_angle_bins-1))
        self.phase_shifts[-1] = -1 * np.pi #round last entry to be exactly pi
        self.angle_bins = np.arcsin(self.phase_shifts / np.pi)

        #mesh grid coordinates for plotting
        self.thetas,self.rhos = np.meshgrid(self.angle_bins,self.range_bins[:self.max_range_bin])
        self.x_s = np.multiply(self.rhos,np.sin(self.thetas))
        self.y_s = np.multiply(self.rhos,np.cos(self.thetas))

        #reload plotting if enabled
        if self.plotting_enabled:
            self._init_video()

        return

    def _init_listeners(self):
        
        #get listener client enabled status
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        #get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        #check enabled status
        self._listener_ADCDataCube_enabled = listener_info["ADCDataCube"]["enabled"]
        self._listener_NormRngAzResp_enabled = listener_info["NormRngAzResp"]["enabled"]
        self._listener_NormRngDopResp_enabled = listener_info["NormRngDopResp"]["enabled"]
        self._listener_RadCloudModel_enabled = listener_info["RadCloudModel"]["enabled"]
        self._listener_PointCloud_enabled = listener_info["PointCloud"]["enabled"]

        self._listeners_enabled = True
        try:

            threads = []

            #setup the respective listeners
            if self._listener_ADCDataCube_enabled:
                self._conn_send_message_to_print("DCA1000Processor._init_listeners: connect ADCDataCube listener")
                t = threading.Thread(target=self._init_ADCDataCube_listener)
                threads.append(t)
                t.start()
            if self._listener_NormRngAzResp_enabled:
                self._conn_send_message_to_print("DCA1000Processor._init_listeners: connect NormRngAzResp listener")
                t = threading.Thread(target=self._init_NormRngAzResp_listener)
                threads.append(t)
                t.start()
            if self._listener_NormRngDopResp_enabled:
                self._conn_send_message_to_print("DCA1000Processor._init_listeners: connect NormRngDopResp listener")
                t = threading.Thread(target=self._init_NormRngDopResp_listener)
                threads.append(t)
                t.start()
            if self._listener_RadCloudModel_enabled:
                self._conn_send_message_to_print("DCA1000Processor._init_listeners: connect RadCloudModel listener")
                t = threading.Thread(target=self._init_RadCloudModel_listener)
                threads.append(t)
                t.start()
            if self._listener_PointCloud_enabled:
                self._conn_send_message_to_print("DCA1000Processor._init_listeners: connect PointCloud listener")
                t = threading.Thread(target=self._init_PointCloud_listener)
                threads.append(t)
                t.start()
            
            for t in threads:
                t.join()
        except AuthenticationError:
            self._conn_send_message_to_print("DCA1000Processor._init_listeners: experienced Authentication error when attempting to connect to Client")
            self._conn_send_parent_error_message()

    def _init_ADCDataCube_listener(self):

        #get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        #get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        ADCDataCube_addr = ('localhost', int(listener_info["ADCDataCube"]["addr"]))
        self._listener_ADCDataCube = Listener(ADCDataCube_addr,authkey=authkey)
        self._conn_ADCDataCube = self._listener_ADCDataCube.accept()
        self._conn_ADCDataCube_enabled = True
    
    def _init_NormRngAzResp_listener(self):

        #get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        #get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        NormRngAzResp_addr = ('localhost', int(listener_info["NormRngAzResp"]["addr"]))
        self._listener_NormRngAzResp = Listener(NormRngAzResp_addr,authkey=authkey)
        self._conn_NormRngAzResp = self._listener_NormRngAzResp.accept()
        self._conn_NormRngAzResp_enabled = True
    
    def _init_NormRngDopResp_listener(self):

        #get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        #get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        NormRngDopResp_addr = ('localhost', int(listener_info["NormRngDopResp"]["addr"]))
        self._listener_NormRngDopResp = Listener(NormRngDopResp_addr,authkey=authkey)
        self._conn_NormRngDopResp = self._listener_NormRngDopResp.accept()
        self._conn_NormRngDopResp_enabled = True
    
    def _init_RadCloudModel_listener(self):

        #get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        #get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        RadCloudModel_addr = ('localhost', int(listener_info["RadCloudModel"]["addr"]))
        self._listener_RadCloudModel = Listener(RadCloudModel_addr,authkey=authkey)
        self._conn_RadCloudModel = self._listener_RadCloudModel.accept()
        self._conn_RadCloudModel_enabled = True
    
    def _init_PointCloud_listener(self):

        #get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        #get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        PointCloud_addr = ('localhost', int(listener_info["PointCloud"]["addr"]))
        self._listener_PointCloud = Listener(PointCloud_addr,authkey=authkey)
        self._conn_PointCloud = self._listener_PointCloud.accept()
        self._conn_PointCloud_enabled = True
#processing packets
    def _process_new_packet(self):
        
        #load the packet into the current_packet byte array
        super()._process_new_packet()
    
        adc_data_cube = self._get_raw_ADC_data_cube()

        range_azimuth_response = self._compute_frame_normalized_range_azimuth_heatmaps(adc_data_cube)

        range_doppler_response = self._compute_normalized_range_doppler_response(adc_data_cube)
        
        #compute point cloud
        if self._conn_RadCloudModel_enabled:
            
            #send range azimuth response to RadCloud model
            try:
                self._conn_RadCloudModel.send(range_azimuth_response)
            except ConnectionResetError:
                self._conn_send_message_to_print("DCA1000 Processor._process_new_packet: Error sending to RadCloud Model")
                self._conn_send_parent_error_message()
                self.streaming_enabled = False
            
            #receive the generated point cloud
            try:
                point_cloud = np.float32(self._conn_RadCloudModel.recv())
            except EOFError:
                self._conn_send_message_to_print("DCA1000 Processor._process_new_packet: Error receiving from RadCloud Model")
                self._conn_send_parent_error_message()
                self.streaming_enabled = False
        
        else:
            point_cloud = None
        
        # if self.plotting_enabled:
        #     #update range azimuth image
        #     video_data_rng_az = np.flip(range_azimuth_response[:,:,0])
        #     video_data_rng_az = (video_data_rng_az * 255).astype(np.uint8)

        #     #resize to make it larger
        #     video_data_rng_az = cv2.resize(video_data_rng_az,
        #                             (self.num_angle_bins * self.zoom,
        #                              self.max_range_bin * self.zoom ))
        #     # update the data with new values
        #     cv2.imshow("Range-Azimuth Response",video_data_rng_az)
        #     cv2.waitKey(1)

        #     #update range doppler image
        #     video_data_rng_dop = np.flip(range_doppler_response)
        #     video_data_rng_dop = (video_data_rng_dop * 255).astype(np.uint8)

        #     video_data_rng_dop = cv2.resize(
        #         video_data_rng_dop,
        #         (self.num_vel_bins * self.zoom,
        #         self.max_range_bin * self.zoom)
        #     )
        #     cv2.imshow("Range-Doppler Response",video_data_rng_dop)
        #     cv2.waitKey(1)
        self._conn_send_data_to_listeners(adc_data_cube, range_azimuth_response,range_doppler_response, point_cloud)
        return
    
    def _conn_send_data_to_listeners(self,
                                     adc_data_cube:np.ndarray,
                                     range_azimuth_response:np.ndarray,
                                     range_doppler_response:np.ndarray,
                                     point_cloud:np.ndarray):
        
        if self._listeners_enabled:
            #send ADC data cube
            try:
                if self._conn_ADCDataCube_enabled:
                    self._conn_ADCDataCube.send(adc_data_cube)
                if self._conn_NormRngAzResp_enabled:
                    self._conn_NormRngAzResp.send(range_azimuth_response)
                if self._conn_NormRngDopResp_enabled:
                    self._conn_NormRngDopResp.send(range_doppler_response)
                if self._conn_PointCloud_enabled:
                    self._conn_PointCloud.send(point_cloud)
            except ConnectionResetError:
                self._conn_send_message_to_print("DCA1000 Processor.__conn_send_data_to_listeners: A listener was already closed or reset")
                self._conn_send_parent_error_message()
                self.streaming_enabled = False
    

    def _get_raw_ADC_data_cube(self):
        """Generate the raw ADC data cube from the streamed packet

        Returns:
            np.ndarray: the raw ADC data cube indexed by [rx_channel, sample, chirp]
        """

        adc_data = np.frombuffer(self.current_packet,dtype=np.int16)

        #reshape to get the real and imaginary parts
        adc_data = np.reshape(adc_data, (DCA1000Processor.LVDS_lanes * 2,-1),order= "F")

        #convert into a complex format
        adc_data = adc_data[0:4,:] + 1j * adc_data[4:,:]
        
        if self.virtual_antennas_enabled:
            #reshape to index as [rx channel, sample, chirp]
            adc_data_cube = np.reshape(adc_data,(self.rx_channels,self.samples_per_chirp,self.total_chirps_per_frame),order="F")

            virtual_array_data_cube = np.zeros_like(adc_data_cube,shape=(self.num_az_antennas,self.samples_per_chirp,self.chirp_loops_per_frame))
            #virtual_array_data_cube = np.zeros((self.num_az_antennas,self.samples_per_chirp,self.chirp_loops_per_frame))

            tx_1_chirps = np.arange(0,self.total_chirps_per_frame,2)
            tx_2_chirps = np.arange(1,self.total_chirps_per_frame,2)

            virtual_array_data_cube[0:self.rx_channels,:,:] = adc_data_cube[:,:,tx_1_chirps]
            virtual_array_data_cube[self.rx_channels:,:,:] = adc_data_cube[:,:,tx_2_chirps]

            return virtual_array_data_cube
        else:
            #reshape to index as [rx channel, sample, chirp]
            adc_data_cube = np.reshape(adc_data,(self.rx_channels,self.samples_per_chirp,self.total_chirps_per_frame),order="F")

            return adc_data_cube
    
    def _compute_frame_normalized_range_azimuth_heatmaps(self,adc_data_cube:np.ndarray):

        frame_range_az_heatmaps = np.zeros((self.max_range_bin,self.num_angle_bins,self.num_chirps_to_save))

        for i in range(self.num_chirps_to_save):
            frame_range_az_heatmaps[:,:,i] = self._compute_chirp_normalized_range_azimuth_heatmap(adc_data_cube,chirp=i)
    
        return frame_range_az_heatmaps
    
    def _compute_chirp_normalized_range_azimuth_heatmap(self,adc_data_cube:np.ndarray,chirp=0):
        """Compute the range azimuth heatmap for a single chirp in the raw ADC data frame

        Args:
            adc_data_cube (np.ndarray): _description_
            chirp (int, optional): _description_. Defaults to 0.

        Returns:
            np.ndarray: the computed range-azimuth heatmap (normalized and thresholded)
        """

        #get range angle cube
        data = np.zeros((self.samples_per_chirp,self.num_angle_bins),dtype=complex)
        data[:,0:self.num_az_antennas] = np.transpose(adc_data_cube[:,:,chirp])

        #compute Range FFT
        data = np.fft.fftshift(np.fft.fft(data,axis=0))

        #compute range response
        data = 20* np.log10(np.abs(np.fft.fftshift(np.fft.fft(data,axis=-1))))

        #[for debugging] to get an idea of what the max should be
        max_db = np.max(data)
        
        #filter to only output the desired ranges
        data = data[:self.max_range_bin,:]

        #perform thresholding on the input data
        data[data <= self.rng_az_power_range_dB[0]] = self.rng_az_power_range_dB[0]
        data[data >= self.rng_az_power_range_dB[1]] = self.rng_az_power_range_dB[1]
        
        #normalize the data
        data = (data - self.rng_az_power_range_dB[0]) / \
            (self.rng_az_power_range_dB[1] - self.rng_az_power_range_dB[0])

        return data
    
    def _compute_normalized_range_doppler_response(self,adc_data_cube:np.ndarray):

        #get the data from a single antenna
        data = adc_data_cube[0,:,:]

        #compute range FFT
        data = np.fft.fftshift(np.fft.fft(data,axis=0))

        #compute doppler FFT
        data = 20 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(data,axis=1))))

        max_db = np.max(data)

        #filter to only the desired output ranges
        data = data[:self.max_range_bin,:]

        #TODO implement thresholding
        #perform thresholding on the input data
        data[data <= self.rng_dop_poer_range_dB[0]] = self.rng_dop_poer_range_dB[0]
        data[data >= self.rng_dop_poer_range_dB[1]] = self.rng_dop_poer_range_dB[1]
        
        #normalize the data
        data = (data - self.rng_dop_poer_range_dB[0]) / \
            (self.rng_dop_poer_range_dB[1] - self.rng_dop_poer_range_dB[0])

        return data




    def _init_video(self):

        #Range-Azimuth Response

        cv2.namedWindow("Range-Azimuth Response",cv2.WINDOW_NORMAL)

        cv2.resizeWindow(
            "Range-Azimuth Response",
            self.num_angle_bins * self.zoom,
            self.max_range_bin * self.zoom)
        
        #Range-Doppler Response
        cv2.namedWindow("Range-Doppler Response",cv2.WINDOW_NORMAL)

        cv2.resizeWindow(
            "Range-Doppler Response",
            self.num_vel_bins * self.zoom,
            self.max_range_bin * self.zoom)

        return
###
###
###
### ARCHIVED CODE: THE FOLLOWING CODE DOES NOT CURRENTLY WORK
###
###
###

    def _init_plots(self):
        if self.plotting_enabled:
            
            #if there was already a figure open, close it so that the new one can be created
            if self.fig != None:
                plt.close(self.fig)
            
            self.fig,self.axs = plt.subplots(2)
            plt.subplots_adjust(hspace=0.6)

            #initialize the full plot
            self.fig.suptitle("Range Azimuth Heatmaps")

            #initialize an array of zero'd data
            dummy_data = np.zeros_like(self.x_s,dtype=float)

            #initialize the cartesian plot
            self.rng_az_cart = self.axs[0].pcolormesh(
                self.x_s,
                self.y_s,
                dummy_data,
                shading='gouraud',
                cmap="gray")
            self.axs[0].set_xlabel('X (m)',fontsize=DCA1000Processor.font_size_axis_labels)
            self.axs[0].set_ylabel('Y (m)',fontsize=DCA1000Processor.font_size_axis_labels)
            self.axs[0].set_title('Range-Azimuth\nHeatmap (Cartesian)',fontsize=DCA1000Processor.font_size_title)

            #initialize the spherical plot
            range_res = range_res = self.radar_performance["range"]["range_res"]
            max_range = self.max_range_bin * range_res
            self.rng_az_sph = self.axs[1].imshow(
                    dummy_data,
                    cmap="gray",
                    extent=[self.angle_bins[-1],self.angle_bins[0],
                            self.range_bins[0],max_range],
                            aspect='auto')
            self.axs[1].set_xlabel('Angle(radians)',fontsize=DCA1000Processor.font_size_axis_labels)
            self.axs[1].set_ylabel('Range (m)',fontsize=DCA1000Processor.font_size_axis_labels)
            self.axs[1].set_title('Range-Azimuth\nHeatmap (Polar)',fontsize=DCA1000Processor.font_size_title)

            self.fig.canvas.draw()
            self.fig.canvas.flush_events()

            return

    def _update_plots(self,rng_az_response:np.ndarray):
        """Update the polar and spherical versions of the range-azimuth response

        Args:
            rng_az_response (np.ndarray): num_range_bins x num_angle_bins normalized range azimuth response
        """

        #update the cartesian plot
        self.rng_az_cart.set_array(rng_az_response)

        #update the spherical plot
        self.rng_az_sph.set_data(np.flip(rng_az_response))

        #update the plots
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()
    
    def _plot_range_azimuth_heatmap_cartesian(self,
                                              rng_az_response:np.ndarray,
                                              ax:plt.Axes=None,
                                              show=True):
        """Plot the range azimuth heatmap (for a single chirp) in cartesian coordinates

        Args:
            rng_az_response (np.ndarray): num_range_bins x num_angle_bins normalized range azimuth response
            ax (plt.Axes, optional): The axis to plot on. If none provided, one is created. Defaults to None.
            show (bool): on True, shows plot. Default to True
        """
        if not ax:
            fig = plt.figure()
            ax = fig.add_subplot()
        
        cartesian_plot = ax.pcolormesh(
            self.x_s,
            self.y_s,
            rng_az_response,
            shading='gouraud',
            cmap="gray")
        ax.set_xlabel('X (m)',fontsize=DCA1000Processor.font_size_axis_labels)
        ax.set_ylabel('Y (m)',fontsize=DCA1000Processor.font_size_axis_labels)
        ax.set_title('Range-Azimuth\nHeatmap (Cartesian)',fontsize=DCA1000Processor.font_size_title)

        if show:
            plt.show()
        
    def _plot_range_azimuth_heatmap_spherical(self,
                                              rng_az_response:np.ndarray,
                                              ax:plt.Axes = None,
                                              show = True):
        """Plot the range azimuth heatmap in spherical coordinates

        Args:
            rng_az_response (np.ndarray): num_range_bins x num_angle_bins normalized range azimuth response
            ax (plt.Axes, optional): The axis to plot on. If none provided, one is created. Defaults to None.
            show (bool): on True, shows plot. Default to True
        """

        if not ax:
            fig = plt.figure()
            ax = fig.add_subplot()

        #plot polar coordinates
        range_res = range_res = self.radar_performance["range"]["range_res"]
        max_range = self.max_range_bin * range_res
        ax.imshow(np.flip(rng_az_response),
                  cmap="gray",
                  extent=[self.angle_bins[-1],self.angle_bins[0],
                          self.range_bins[0],max_range],
                          aspect='auto')
        ax.set_xlabel('Angle(radians)',fontsize=DCA1000Processor.font_size_axis_labels)
        ax.set_ylabel('Range (m)',fontsize=DCA1000Processor.font_size_axis_labels)
        ax.set_title('Range-Azimuth\nHeatmap (Polar)',fontsize=DCA1000Processor.font_size_title)

        #if enable_color_bar:
        #    cbar = self.fig.colorbar(polar_plt)
        #    cbar.set_label("Relative Power (dB)",size=RadarDataProcessor.font_size_color_bar)
        #    cbar.ax.tick_params(labelsize=RadarDataProcessor.font_size_color_bar)
        if show:
            plt.show()


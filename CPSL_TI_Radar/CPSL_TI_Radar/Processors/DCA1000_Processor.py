from multiprocessing.connection import Connection
from multiprocessing import connection, AuthenticationError

import numpy as np
from multiprocessing.connection import Listener
import threading

from CPSL_TI_Radar.Processors._Processor import _Processor


class DCA1000Processor(_Processor):
    LVDS_lanes = 4

    # plotting parameters
    font_size_title = 14
    font_size_axis_labels = 12
    font_size_color_bar = 10

    def __init__(
        self,
        conn_parent: Connection,
        conn_processor_data: Connection,
        settings_file_path="config_Radar.json",
    ):
        """Initialization process for DCA1000 Processor class

        Args:
            conn_parent (connection): connection to the parent process (RADAR)
            conn_processor_data (Connection): connection to pass data between Processors and Streamers.
            settings_file_path (str, optional): path to the RADAR config file. Defaults to 'config_RADAR.json'.
        """

        super().__init__(
            conn_parent=conn_parent,
            settings_file_path=settings_file_path,
            conn_processor_data=conn_processor_data,
        )

        self.current_packet = bytearray()

        # key radar parameters
        # TODO: enable these at a later time
        self.max_range_bin = 64  # enable this a bit better
        self.num_chirps_to_save = 0  # set from config
        self.num_angle_bins = 64
        self.rng_dop_poer_range_dB = [70, 140]

        # key angular radar parameters
        self.rx_channels = 0
        self.num_az_antennas = 0
        self.virtual_antennas_enabled = 0

        # number of chirps per loop and chirp loops per frame
        self.chirps_per_loop = 0
        self.chirp_loops_per_frame = 0
        self.total_chirps_per_frame = 0
        self.samples_per_chirp = 0

        # compute range bins
        self.range_bins = None

        # velocity bins
        self.num_vel_bins = 0
        self.velocity_bins = None

        # compute angular parameters
        self.AoA_method = "FFT" #'FFT','Bartlet','Capon'
        self.angle_bins = None

        #specify power ranges
        self.rng_az_power_range_dB_FFT = [67, 105]
        self.rng_az_power_range_dB_Bartlet = [120,200]
        self.rng_az_power_range_dB_Capon = [50,95]

        
        #capon and bartlet transform variables
        self.angle_range_deg = [-90,90]
        self.spatial_signatures = None
        self.a_phi = None
        self.a_phi_H = None

        # mesh grid coordinates for plotting
        self.thetas = None
        self.rhos = None
        self.x_s = None
        self.y_s = None

        # listeners
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

        self._conn_send_init_status(self.init_success)
        self.run()

        return

    def close(self):
        pass

    def _load_new_config(self, config_info: dict):
        # call the parent class method to save the new radar config and performance
        super()._load_new_config(config_info)

        # key radar parameters
        self.rx_channels = self.radar_performance["angle"]["num_rx_antennas"]
        self.num_az_antennas = self.radar_performance["angle"]["num_az_antennas"]
        self.virtual_antennas_enabled = self.radar_performance["angle"][
            "virtual_anetnnas_enabled"
        ]

        # number of chirps per loop and chirp loops per frame
        chirp_start_profile_idx = int(self.radar_config["frameCfg"]["startIndex"])
        chirp_end_profile_idx = int(self.radar_config["frameCfg"]["endIndex"])
        self.chirps_per_loop = chirp_end_profile_idx - chirp_start_profile_idx + 1
        self.chirp_loops_per_frame = int(self.radar_config["frameCfg"]["loops"])
        # TODO: currently hardcoded to the number of chirps in a frame although this can be adjusted
        self.num_chirps_to_save = self.chirp_loops_per_frame
        self.total_chirps_per_frame = self.chirp_loops_per_frame * self.chirps_per_loop
        self.samples_per_chirp = int(self.radar_config["profileCfg"]["adcSamples"])

        # compute range bins
        range_res = self.radar_performance["range"]["range_res"]
        self.range_bins = np.arange(0, self.samples_per_chirp) * range_res

        # compute doppler bins
        vel_res = self.radar_performance["velocity"]["vel_res"]
        vel_max = self.radar_performance["velocity"]["vel_max"]
        self.num_vel_bins = int(self.radar_performance["velocity"]["num_doppler_bins"])
        self.velocity_bins = np.arange(-1 * vel_max, vel_max, vel_res)

        self._init_AoA_compute_method()

        self._init_plot_grid()
        
        return
    
    def _init_plot_grid(self):
        """Initialize the grid for plotting in cartesian/polar (assumes angle/range bins already defined)
        """
        # mesh grid coordinates for plotting
        self.thetas, self.rhos = np.meshgrid(
            self.angle_bins, self.range_bins[: self.max_range_bin]
        )
        self.x_s = np.multiply(self.rhos, np.sin(self.thetas))
        self.y_s = np.multiply(self.rhos, np.cos(self.thetas))


    def _init_AoA_compute_method(self):

        method = self._settings["Processor"]["AoA_Processor"]

        match method:
            case "FFT":
                self.AoA_method = "FFT"
                self._init_AoA_FFT()
            case "Bartlet":
                self.AoA_method = "Bartlet"
                self._init_AoA_Bartlet_Capon()
            case "Capon":
                self.AoA_method = "Capon"
                self._init_AoA_Bartlet_Capon()
            case _:
                self._conn_send_message_to_print("DCA1000_Processor._init_AoA_compute_method: did not receive valid AoA method")
                self._conn_send_parent_error_message()
                return
    
    def _init_AoA_FFT(self):

        #get the range of potential phase shifts
        phase_shifts = np.arange(
            np.pi,
            -np.pi - 2 * np.pi / (self.num_angle_bins - 1),
            -2 * np.pi / (self.num_angle_bins - 1),
        )
        phase_shifts[-1] = -1 * np.pi  # round last entry to be exactly pi
        
        #convert the phase shifts to their respective AoA bins
        self.angle_bins = np.arcsin(phase_shifts / np.pi)
    
    def  _init_AoA_Bartlet_Capon(self):

        #get the step size for the angle bins
        step = (self.angle_range_deg[1] - self.angle_range_deg[0]) / self.num_angle_bins
        angles_deg = np.arange(self.angle_range_deg[0],self.angle_range_deg[1],step)
        self.angle_bins = np.deg2rad(angles_deg)

        #compute the spatial signatures
        self.a_phi = self._compute_spatial_signatures(self.angle_bins)
        self.a_phi_H = np.conj(np.transpose(self.a_phi,axes=(0,2,1)))


    def _compute_spatial_signature(self,angle_rad):
        """Compute the spatial signature for the Capon/Bartlet methods for a 
        linear array geometry at a specific angle with lambda/2 spacing between elements

        Args:
            angle_rad (_type_): the angle to compute the spatial signature at

        Returns:
            np.ndarray(dtype=np.complex_): spatial signature with num_az_antennas elements
        """
        indicies = np.arange(0,self.num_az_antennas,dtype=np.float32)
        spatial_signature = np.exp(1j * np.pi * indicies * np.sin(angle_rad))

        return spatial_signature
    
    def _compute_spatial_signatures(self,angles_rad:np.ndarray):
        """Compute the spatial signatures used by the Capon and Bartlet AoA estimation techniques for a given set of AoA's

        Args:
            angles_rad (np.ndarray): Array of angles to compute the spatial signatures at

        Returns:
            np.ndarray: num_angle_bins x num_az_antennas x 1 array of spatial signatures
            which can easily be used for np.matmul() operations
        """

        spatial_signatures = np.zeros(
            shape=(self.num_angle_bins,self.num_az_antennas,1),
            dtype=np.complex_)

        for i in range(len(angles_rad)):
            spatial_signatures[i,:,0] = self._compute_spatial_signature(angles_rad[i])
        
        return spatial_signatures
    
    def _init_listeners(self):
        # get listener client enabled status
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        # get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        # check enabled status
        self._listener_ADCDataCube_enabled = listener_info["ADCDataCube"]["enabled"]
        self._listener_NormRngAzResp_enabled = listener_info["NormRngAzResp"]["enabled"]
        self._listener_NormRngDopResp_enabled = listener_info["NormRngDopResp"][
            "enabled"
        ]
        self._listener_RadCloudModel_enabled = listener_info["RadCloudModel"]["enabled"]
        self._listener_PointCloud_enabled = listener_info["PointCloud"]["enabled"]

        self._listeners_enabled = True
        try:
            threads = []

            # setup the respective listeners
            if self._listener_ADCDataCube_enabled:
                self._conn_send_message_to_print(
                    "DCA1000Processor._init_listeners: connect ADCDataCube listener"
                )
                t = threading.Thread(target=self._init_ADCDataCube_listener)
                threads.append(t)
                t.start()
            if self._listener_NormRngAzResp_enabled:
                self._conn_send_message_to_print(
                    "DCA1000Processor._init_listeners: connect NormRngAzResp listener"
                )
                t = threading.Thread(target=self._init_NormRngAzResp_listener)
                threads.append(t)
                t.start()
            if self._listener_NormRngDopResp_enabled:
                self._conn_send_message_to_print(
                    "DCA1000Processor._init_listeners: connect NormRngDopResp listener"
                )
                t = threading.Thread(target=self._init_NormRngDopResp_listener)
                threads.append(t)
                t.start()
            if self._listener_RadCloudModel_enabled:
                self._conn_send_message_to_print(
                    "DCA1000Processor._init_listeners: connect RadCloudModel listener"
                )
                t = threading.Thread(target=self._init_RadCloudModel_listener)
                threads.append(t)
                t.start()
            if self._listener_PointCloud_enabled:
                self._conn_send_message_to_print(
                    "DCA1000Processor._init_listeners: connect PointCloud listener"
                )
                t = threading.Thread(target=self._init_PointCloud_listener)
                threads.append(t)
                t.start()

            for t in threads:
                t.join()
        except AuthenticationError:
            self._conn_send_message_to_print(
                "DCA1000Processor._init_listeners: experienced Authentication error when attempting to connect to Client"
            )
            self._conn_send_parent_error_message()

    def _init_ADCDataCube_listener(self):
        # get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        # get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        ADCDataCube_addr = ("localhost", int(listener_info["ADCDataCube"]["addr"]))
        self._listener_ADCDataCube = Listener(ADCDataCube_addr, authkey=authkey)
        self._conn_ADCDataCube = self._listener_ADCDataCube.accept()
        self._conn_ADCDataCube_enabled = True

    def _init_NormRngAzResp_listener(self):
        # get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        # get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        NormRngAzResp_addr = ("localhost", int(listener_info["NormRngAzResp"]["addr"]))
        self._listener_NormRngAzResp = Listener(NormRngAzResp_addr, authkey=authkey)
        self._conn_NormRngAzResp = self._listener_NormRngAzResp.accept()
        self._conn_NormRngAzResp_enabled = True

    def _init_NormRngDopResp_listener(self):
        # get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        # get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        NormRngDopResp_addr = (
            "localhost",
            int(listener_info["NormRngDopResp"]["addr"]),
        )
        self._listener_NormRngDopResp = Listener(NormRngDopResp_addr, authkey=authkey)
        self._conn_NormRngDopResp = self._listener_NormRngDopResp.accept()
        self._conn_NormRngDopResp_enabled = True

    def _init_RadCloudModel_listener(self):
        # get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        # get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        RadCloudModel_addr = ("localhost", int(listener_info["RadCloudModel"]["addr"]))
        self._listener_RadCloudModel = Listener(RadCloudModel_addr, authkey=authkey)
        self._conn_RadCloudModel = self._listener_RadCloudModel.accept()
        self._conn_RadCloudModel_enabled = True

    def _init_PointCloud_listener(self):
        # get listener info
        listener_info = self._settings["Processor"]["DCA1000_Listeners"]

        # get the authentication string
        authkey_str = listener_info["authkey"]
        authkey = authkey_str.encode()

        PointCloud_addr = ("localhost", int(listener_info["PointCloud"]["addr"]))
        self._listener_PointCloud = Listener(PointCloud_addr, authkey=authkey)
        self._conn_PointCloud = self._listener_PointCloud.accept()
        self._conn_PointCloud_enabled = True

    # processing packets
    def _process_new_packet(self):
        # load the packet into the current_packet byte array
        super()._process_new_packet()

        adc_data_cube = self._get_raw_ADC_data_cube()

        range_azimuth_response = self._compute_normalized_range_azimuth_heatmap(
            adc_data_cube
        )

        range_doppler_response = self._compute_normalized_range_doppler_response(
            adc_data_cube
        )

        # compute point cloud
        if self._conn_RadCloudModel_enabled:
            # send range azimuth response to RadCloud model
            try:
                self._conn_RadCloudModel.send(range_azimuth_response)
            except ConnectionResetError:
                self._conn_send_message_to_print(
                    "DCA1000 Processor._process_new_packet: Error sending to RadCloud Model"
                )
                self._conn_send_parent_error_message()
                self.streaming_enabled = False

            # receive the generated point cloud
            try:
                point_cloud = np.float32(self._conn_RadCloudModel.recv())
            except EOFError:
                self._conn_send_message_to_print(
                    "DCA1000 Processor._process_new_packet: Error receiving from RadCloud Model"
                )
                self._conn_send_parent_error_message()
                self.streaming_enabled = False

        else:
            point_cloud = None

        self._conn_send_data_to_listeners(
            adc_data_cube, range_azimuth_response, range_doppler_response, point_cloud
        )
        return

    def _conn_send_data_to_listeners(
        self,
        adc_data_cube: np.ndarray,
        range_azimuth_response: np.ndarray,
        range_doppler_response: np.ndarray,
        point_cloud: np.ndarray,
    ):
        if self._listeners_enabled:
            # send ADC data cube
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
                self._conn_send_message_to_print(
                    "DCA1000 Processor.__conn_send_data_to_listeners: A listener was already closed or reset"
                )
                self._conn_send_parent_error_message()
                self.streaming_enabled = False

    def _get_raw_ADC_data_cube(self):
        """Generate the raw ADC data cube from the streamed packet

        Returns:
            np.ndarray: the raw ADC data cube indexed by [rx_channel, sample, chirp]
        """

        adc_data = np.frombuffer(self.current_packet, dtype=np.int16)

        # reshape to get the real and imaginary parts
        adc_data = np.reshape(
            adc_data, (DCA1000Processor.LVDS_lanes * 2, -1), order="F"
        )

        # convert into a complex format
        adc_data = adc_data[0:4, :] + 1j * adc_data[4:, :]

        if self.virtual_antennas_enabled:
            # reshape to index as [rx channel, sample, chirp]
            adc_data_cube = np.reshape(
                adc_data,
                (self.rx_channels, self.samples_per_chirp, self.total_chirps_per_frame),
                order="F",
            )

            virtual_array_data_cube = np.zeros_like(
                adc_data_cube,
                shape=(
                    self.num_az_antennas,
                    self.samples_per_chirp,
                    self.chirp_loops_per_frame,
                ),
            )
            # virtual_array_data_cube = np.zeros((self.num_az_antennas,self.samples_per_chirp,self.chirp_loops_per_frame))

            tx_1_chirps = np.arange(0, self.total_chirps_per_frame, 2)
            tx_2_chirps = np.arange(1, self.total_chirps_per_frame, 2)

            virtual_array_data_cube[0 : self.rx_channels, :, :] = adc_data_cube[
                :, :, tx_1_chirps
            ]
            virtual_array_data_cube[self.rx_channels :, :, :] = adc_data_cube[
                :, :, tx_2_chirps
            ]

            return virtual_array_data_cube
        else:
            # reshape to index as [rx channel, sample, chirp]
            adc_data_cube = np.reshape(
                adc_data,
                (self.rx_channels, self.samples_per_chirp, self.total_chirps_per_frame),
                order="F",
            )

            return adc_data_cube

    def _compute_normalized_range_azimuth_heatmap(self,adc_data_cube:np.ndarray):

        #use the appropriate range-azimuth heatmap computation method
        match self.AoA_method:
            case "FFT":
                return self._compute_normalized_range_azimuth_heatmap_FFT(adc_data_cube)
            case "Bartlet":
                return self._compute_normalized_range_azimuth_heatmap_bartlet(adc_data_cube)
            case "Capon":
                return self._compute_normalized_range_azimuth_heatmap_capon(adc_data_cube)

    def _compute_normalized_range_azimuth_heatmap_FFT(
        self, adc_data_cube: np.ndarray
    ):
        frame_range_az_heatmaps = np.zeros(
            (self.max_range_bin, self.num_angle_bins, self.num_chirps_to_save)
        )

        for i in range(self.num_chirps_to_save):
            frame_range_az_heatmaps[
                :, :, i
            ] = self._compute_chirp_normalized_range_azimuth_heatmap_FFT(
                adc_data_cube, chirp=i
            )

        return frame_range_az_heatmaps
    

    def _compute_chirp_normalized_range_azimuth_heatmap_FFT(
        self, adc_data_cube: np.ndarray, chirp=0
    ):
        """Compute the range azimuth heatmap for a single chirp in the raw ADC data frame

        Args:
            adc_data_cube (np.ndarray): _description_
            chirp (int, optional): _description_. Defaults to 0.

        Returns:
            np.ndarray: the computed range-azimuth heatmap (normalized and thresholded)
        """

        # get range angle cube
        data = np.zeros((self.samples_per_chirp, self.num_angle_bins), dtype=complex)
        data[:, 0 : self.num_az_antennas] = np.transpose(adc_data_cube[:, :, chirp])

        # compute Range FFT
        data = np.fft.fftshift(np.fft.fft(data, axis=0))

        # compute azimuth response
        data = 20 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(data, axis=-1))))

        # [for debugging] to get an idea of what the max should be
        max_db = np.max(data)

        # filter to only output the desired ranges
        data = data[: self.max_range_bin, :]

        # perform thresholding on the input data
        data[data <= self.rng_az_power_range_dB_FFT[0]] = self.rng_az_power_range_dB_FFT[0]
        data[data >= self.rng_az_power_range_dB_FFT[1]] = self.rng_az_power_range_dB_FFT[1]

        # normalize the data
        data = (data - self.rng_az_power_range_dB_FFT[0]) / (
            self.rng_az_power_range_dB_FFT[1] - self.rng_az_power_range_dB_FFT[0]
        )

        return data
    
    def _compute_normalized_range_azimuth_heatmap_bartlet(
        self, adc_data_cube: np.ndarray
    ):
        """Compute the normalized range-azimuth heatmap using the bartlet method

        Args:
            adc_data_cube (np.ndarray): num_Rx_antennas x num_adc_samples x num_chirps ADC data cube

        Returns:
            np.ndarray: num_range_bins x num_angle_bins x 1 range-azimuth response using bartlet method
        """
        #get the ADC data cube into the correct format
        adc_data_cube = np.transpose(adc_data_cube,axes=(1,0,2))
        
        #compute the range FFT
        rng_fft = np.fft.fft(adc_data_cube,axis=0)

        L_rng_bins = np.shape(adc_data_cube)[0]
        I_angle_bins = self.num_angle_bins
        p_bartlet = np.zeros(
            shape=(L_rng_bins,I_angle_bins),dtype=np.complex_)
        
        for l in range(L_rng_bins):
            # x_n = np.transpose(rng_fft[l,:,:,np.newaxis],axes=(1,0,2))
            x_n = np.expand_dims(np.transpose(rng_fft[l,:,:]),axis=-1) #NxMx1
            x_n_h = np.conj(np.transpose(x_n,axes=(0,2,1)))

            Rxx = np.mean(np.matmul(x_n,x_n_h),axis=0)

            p = self.a_phi_H @ Rxx @ self.a_phi

            p_bartlet[l,:] = p[:,0,0]

        #convert to dB
        p_bartlet = 20 * np.log10(np.abs(p_bartlet))

        # filter to only output the desired ranges
        p_bartlet = p_bartlet[: self.max_range_bin, :]

        # perform thresholding on the input data
        p_bartlet[p_bartlet <= self.rng_az_power_range_dB_Bartlet[0]] = self.rng_az_power_range_dB_Bartlet[0]
        p_bartlet[p_bartlet >= self.rng_az_power_range_dB_Bartlet[1]] = self.rng_az_power_range_dB_Bartlet[1]

        # normalize the data
        p_bartlet = (p_bartlet - self.rng_az_power_range_dB_Bartlet[0]) / (
            self.rng_az_power_range_dB_Bartlet[1] - self.rng_az_power_range_dB_Bartlet[0]
        )
        
        #expand the dimmentsions to align with the other formats
        p_bartlet = np.expand_dims(p_bartlet,axis=-1)
        return p_bartlet
    
    def _compute_normalized_range_azimuth_heatmap_capon(
        self, adc_data_cube: np.ndarray
    ):
        """Compute the normalized range-azimuth heatmap using the Capon method

        Args:
            adc_data_cube (np.ndarray): num_Rx_antennas x num_adc_samples x num_chirps ADC data cube

        Returns:
            np.ndarray: num_range_bins x num_angle_bins x 1 range-azimuth response using capon method
        """
        #get the ADC data cube into the correct format
        adc_data_cube = np.transpose(adc_data_cube,axes=(1,0,2))
        
        #compute the range FFT
        rng_fft = np.fft.fft(adc_data_cube,axis=0)

        L_rng_bins = np.shape(adc_data_cube)[0]
        I_angle_bins = self.num_angle_bins
        p_capon = np.zeros(
            shape=(L_rng_bins,I_angle_bins),dtype=np.complex_)
        
        for l in range(L_rng_bins):
            # x_n = np.transpose(rng_fft[l,:,:,np.newaxis],axes=(1,0,2))
            x_n = np.expand_dims(np.transpose(rng_fft[l,:,:]),axis=-1) #NxMx1
            x_n_h = np.conj(np.transpose(x_n,axes=(0,2,1)))

            Rxx = np.mean(np.matmul(x_n,x_n_h),axis=0)
            Rxx_inv = np.linalg.inv(Rxx)

            p = self.a_phi_H @ Rxx_inv @ self.a_phi

            p_capon[l,:] = 1.0 / p[:,0,0]

        #convert to dB
        p_capon = 20 * np.log10(np.abs(p_capon))

        # filter to only output the desired ranges
        p_capon = p_capon[: self.max_range_bin, :]

        # perform thresholding on the input data
        p_capon[p_capon <= self.rng_az_power_range_dB_Capon[0]] = self.rng_az_power_range_dB_Capon[0]
        p_capon[p_capon >= self.rng_az_power_range_dB_Capon[1]] = self.rng_az_power_range_dB_Capon[1]

        # normalize the data
        p_capon = (p_capon - self.rng_az_power_range_dB_Capon[0]) / (
            self.rng_az_power_range_dB_Capon[1] - self.rng_az_power_range_dB_Capon[0]
        )
        
        #expand the dimmentsions to align with the other formats
        p_capon = np.expand_dims(p_capon,axis=-1)
        return p_capon

    def _compute_normalized_range_doppler_response(self, adc_data_cube: np.ndarray):
        # get the data from a single antenna
        data = adc_data_cube[0, :, :]

        # compute range FFT
        data = np.fft.fftshift(np.fft.fft(data, axis=0))

        # compute doppler FFT
        data = 20 * np.log10(np.abs(np.fft.fftshift(np.fft.fft(data, axis=1))))

        max_db = np.max(data)

        # filter to only the desired output ranges
        data = data[: self.max_range_bin, :]

        # TODO implement thresholding
        # perform thresholding on the input data
        data[data <= self.rng_dop_poer_range_dB[0]] = self.rng_dop_poer_range_dB[0]
        data[data >= self.rng_dop_poer_range_dB[1]] = self.rng_dop_poer_range_dB[1]

        # normalize the data
        data = (data - self.rng_dop_poer_range_dB[0]) / (
            self.rng_dop_poer_range_dB[1] - self.rng_dop_poer_range_dB[0]
        )

        return data

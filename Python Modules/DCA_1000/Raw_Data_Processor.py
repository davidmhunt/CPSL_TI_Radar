import os
import numpy as np
from scipy.constants import c,pi
import matplotlib.pyplot as plt
import imageio
import io
from IPython.display import display, clear_output
from tqdm import tqdm

class RawDataProcessor:
    
    #global params

    #angular FFT params
    num_angle_bins = 64

    #plotting parameters
    font_size_title = 14
    font_size_axis_labels = 12
    font_size_color_bar = 10

    def __init__(self):
        
        #given radar parameters
        self.chirps_per_frame = None
        self.rx_channels = None
        self.tx_channels = None
        self.samples_per_chirp = None
        self.adc_sample_rate_Hz = None
        self.chirp_slope_MHz_us = None
        self.start_freq_Hz = None
        self.idle_time_us = None
        self.ramp_end_time_us = None

        #computed radar parameters
        self.chirp_BW_Hz = None

        #computed radar performance specs
        self.range_res = None
        self.ranges = None
        self.phase_shifts = None
        self.angle_bins = None
        self.thetas = None
        self.rhos = None
        self.x_s = None
        self.y_s = None

        #raw radar cube (indexed by [rx channel, sample, chirp, frame])
        self.adc_data_cube = None
        self.num_frames = None

        #plotting
        self.fig = None
        self.axs = None
        
        #variables for saving a gif
        self.save_as_gif_enabled = None #TODO:implement this ability
        self.gif_file_name = "GeneratedHeatMap.gif"
        self.image_frames = None
        self.frame_duration = None
        self.hdisplay = None

        return

    def set_config_params(self,
                          chirps_per_frame,
                          rx_channels,
                          tx_channels,
                          samples_per_chirp,
                          adc_sample_rate_Hz,
                          chirp_slope_MHz_us,
                          start_freq_Hz,
                          idle_time_us,
                          ramp_end_time_us):
        #load the parameters

        self.chirps_per_frame = chirps_per_frame
        self.rx_channels = rx_channels
        self.tx_channels = tx_channels
        self.samples_per_chirp = samples_per_chirp
        self.adc_sample_rate_Hz = adc_sample_rate_Hz
        self.chirp_slope_MHz_us = chirp_slope_MHz_us
        self.start_freq_Hz = start_freq_Hz
        self.idle_time_us = idle_time_us
        self.ramp_end_time_us = ramp_end_time_us

        #compute other parameters
        

        #init computed params
        self.init_computed_params()
    
    def set_config_params_from_cfg_file(self):
        print("RawDataProcessor.load_config_from_cfg: Function not yet implemented")
        pass

    def init_computed_params(self):

        #chirp BW
        self.chirp_BW_Hz = self.chirp_slope_MHz_us * 1e12 * self.samples_per_chirp / self.adc_sample_rate_Hz

        #range resolution
        self.range_res = c / (2 * self.chirp_BW_Hz)
        self.ranges = np.arange(0,self.samples_per_chirp) * self.range_res

        #angular parameters
        self.phase_shifts = np.arange(pi,-pi  - 2 * pi /(RawDataProcessor.num_angle_bins - 1),-2 * pi / (RawDataProcessor.num_angle_bins-1))
        self.angle_bins = np.arcsin(self.phase_shifts / pi)
        
        #mesh grid coordinates for plotting
        self.thetas,self.rhos = np.meshgrid(self.angle_bins,self.ranges)
        self.x_s = np.multiply(self.rhos,np.sin(self.thetas))
        self.y_s = np.multiply(self.rhos,np.cos(self.thetas))

    def load_data_from_DCA1000(self,file_path):
        
        #import the raw data
        LVDS_lanes = 4
        adc_data = np.fromfile(file_path,dtype=np.int16)

        #reshape to get the real and imaginary parts
        adc_data = np.reshape(adc_data, (LVDS_lanes * 2,-1),order= "F")

        #convert into a complex format
        adc_data = adc_data[0:4,:] + 1j * adc_data[4:,:]

        #reshape to index as [rx channel, sample, chirp, frame]
        self.adc_data_cube = np.reshape(adc_data,(self.rx_channels,self.samples_per_chirp,self.chirps_per_frame,-1),order="F")
        self.num_frames = self.adc_data_cube.shape[3]

    def load_frame_from_DeepSense6G(self,radar_cube:np.array):

        self.num_frames = 1
        self.adc_data_cube = radar_cube[:,:,:,np.newaxis]

    def compute_range_azimuth_heatmap(self,frame,chirp=0):

        #get range angle cube
        data = np.zeros((self.samples_per_chirp,RawDataProcessor.num_angle_bins),dtype=complex)
        data[:,0:self.rx_channels] = np.transpose(self.adc_data_cube[:,:,chirp,frame])

        #compute Range FFT
        data = np.fft.fftshift(np.fft.fft(data,axis=0))

        #compute range response
        data = 20* np.log10(np.abs(np.fft.fftshift(np.fft.fft(data,axis=-1))))

        return data
    
    def plot_range_azimuth_heatmap(self,
                                   frame,
                                   chirp=0,
                                   enable_color_bar = True,
                                   cutoff_val_dB = 30,
                                   range_lims = None,
                                   jupyter = False):
        
        #compute the range azimuth response
        range_azimuth_response = self.compute_range_azimuth_heatmap(frame,chirp)

        #determine a min value to plot
        v_min = np.max(range_azimuth_response) - cutoff_val_dB

        #determine the ranges at which to generate the plot
        if range_lims:
            min_rng_idx = int(np.ceil(range_lims[0]/self.range_res))
            max_rng_idx = int(np.floor(range_lims[1]/self.range_res))
        else:
            min_rng_idx = 0
            max_rng_idx = self.samples_per_chirp - 1

        #create the plot
        self.fig,self.axs = plt.subplots(nrows=1,ncols=2,figsize=(8,4))

        #improve spacing between subplots
        self.fig.subplots_adjust(wspace=0.4)

        #plot polar coordinates
        polar_plt = self.axs[0].pcolormesh(self.thetas[min_rng_idx:max_rng_idx,:],self.rhos[min_rng_idx:max_rng_idx,:],range_azimuth_response[min_rng_idx:max_rng_idx,:],cmap="gray",vmin=v_min)
        self.axs[0].set_xlabel('Angle(radians)',fontsize=RawDataProcessor.font_size_axis_labels)
        self.axs[0].set_ylabel('Range (m)',fontsize=RawDataProcessor.font_size_axis_labels)
        self.axs[0].set_title('Range-Azimuth\nHeatmap (Polar)',fontsize=RawDataProcessor.font_size_title)

        if enable_color_bar:
            cbar = self.fig.colorbar(polar_plt)
            cbar.set_label("Relative Power (dB)",size=RawDataProcessor.font_size_color_bar)
            cbar.ax.tick_params(labelsize=RawDataProcessor.font_size_color_bar)

        #convert polar to cartesian
        cartesian_plot = self.axs[1].pcolormesh(self.x_s[min_rng_idx:max_rng_idx,:],self.y_s[min_rng_idx:max_rng_idx,:],range_azimuth_response[min_rng_idx:max_rng_idx,:],shading='gouraud',cmap="gray",vmin = v_min)
        self.axs[1].set_xlabel('X (m)',fontsize=RawDataProcessor.font_size_axis_labels)
        self.axs[1].set_ylabel('Y (m)',fontsize=RawDataProcessor.font_size_axis_labels)
        self.axs[1].set_title('Range-Azimuth\nHeatmap (Cartesian)',fontsize=RawDataProcessor.font_size_title)

        if enable_color_bar:
            cbar = self.fig.colorbar(cartesian_plot)
            cbar.set_label("Relative Power (dB)",size=RawDataProcessor.font_size_color_bar)
            cbar.ax.tick_params(labelsize=RawDataProcessor.font_size_color_bar)

    
    def _init_save_to_gif(self, frame_duration_s):
        #initialize the image frames
        self.image_frames = []
        self.frame_duration = frame_duration_s
    
    def _save_gif_to_file(self):
        #save to a gif
        imageio.mimsave(self.gif_file_name,self.image_frames,duration=self.frame_duration,loop=0)

    def generate_gif(self,
                    frame_period_s,
                    enable_color_bar = True,
                    cutoff_val_dB = 30,
                    range_lims = None,
                    jupyter = False):
        
        #initialize the ability to save to a .gif file
        self._init_save_to_gif(frame_period_s)

        if jupyter:
            self.hdisplay = display("",display_id=True)
            plt.ioff()

        for i in tqdm(range(self.num_frames)):
            #plot the heatmap
            self.plot_range_azimuth_heatmap(frame=i,
                                            chirp=0,
                                            enable_color_bar=enable_color_bar,
                                            cutoff_val_dB=cutoff_val_dB,
                                            range_lims=range_lims,
                                            jupyter=jupyter)

            buf = io.BytesIO()
            self.fig.savefig(buf,format='png',dpi=300)
            buf.seek(0)
            self.image_frames.append(imageio.imread(buf))
            plt.close(self.fig)
        
        self._save_gif_to_file()






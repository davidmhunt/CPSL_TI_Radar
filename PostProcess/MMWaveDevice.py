import json
import numpy as np
import os

class MMWaveDevice:
    def __init__(self, adc_data_bin_file, mmwave_setup_json_file, profile_id=0):
        sys_param_json = json.load(open(mmwave_setup_json_file))
        
        mmWaveDevices = sys_param_json["mmWaveDevices"][0]
        rfConfig = mmWaveDevices["rfConfig"]
        profiles = rfConfig["rlProfiles"]

        profile = profiles[profile_id]["rlProfileCfg_t"]
        self.freq = profile["startFreqConst_GHz"] * 1e9
        self.lambda_ = 3e8 / self.freq
        
        self.num_byte_per_sample = 4 
        self.rx_chanl_enable = int(rfConfig["rlChanCfg_t"]["rxChannelEn"], 16)
        self.num_rx_chnl = bin(self.rx_chanl_enable).count('1')
        
        self.num_sample_per_chirp = profile["numAdcSamples"]
        self.num_chirp_per_frame = rfConfig["rlFrameCfg_t"]["numLoops"]

        self.win_hann = np.hanning(self.num_sample_per_chirp)
        
        self.size_per_frame = self.num_byte_per_sample * self.num_rx_chnl * self.num_sample_per_chirp * self.num_chirp_per_frame
        
        bin_file = adc_data_bin_file
        bin_file_size = os.path.getsize(bin_file)
        
        self.num_frame = (bin_file_size // self.size_per_frame )// profiles.__len__()
        self.num_sample_per_frame = self.num_rx_chnl * self.num_chirp_per_frame * self.num_sample_per_chirp

        self.adc_samp_rate = profile["digOutSampleRate"] / 1e3

        if "fmt" in rfConfig["rlAdcOutCfg_t"] and "b2AdcBits" in rfConfig["rlAdcOutCfg_t"]["fmt"]:
            if rfConfig["rlAdcOutCfg_t"]["fmt"]["b2AdcBits"] == 2:
                self.adc_bits = 16
            else:
                self.adc_bits = 14
        else:
            self.adc_bits = 16 

        self.dbfs_coeff = -(20 * np.log10(2**(self.adc_bits - 1)) + 20 * np.log10(sum(self.win_hann)) - 20 * np.log10(np.sqrt(2)))

        self.chirp_slope = profile["freqSlopeConst_MHz_usec"]
        self.bw = self.chirp_slope * self.num_sample_per_chirp / self.adc_samp_rate
        self.chirp_ramp_time = profile["rampEndTime_usec"]
        self.chirp_idle_time = profile["idleTimeConst_usec"]
        self.chirp_adc_start_time = profile["adcStartTimeConst_usec"]
        self.frame_periodicity = rfConfig["rlFrameCfg_t"]["framePeriodicity_msec"]

        self.range_max = 3e8 * self.adc_samp_rate * 1e6 / (2 * self.chirp_slope * 1e12)
        self.range_res = 3e8 / (2 * self.bw * 1e6)

        self.v_max = self.lambda_ / (4 * (self.chirp_ramp_time + self.chirp_idle_time) * 1e-6)
        self.v_res = self.lambda_ / (2 * self.num_chirp_per_frame * (self.chirp_ramp_time + self.chirp_idle_time) * 1e-6)

        self.is_iq_swap = mmWaveDevices["rawDataCaptureConfig"]["rlDevDataFmtCfg_t"]["iqSwapSel"]
        self.is_interleave = mmWaveDevices["rawDataCaptureConfig"]["rlDevDataFmtCfg_t"]["chInterleave"]

    def print_device_configuration(self):
        print(f'# of sample/chirp: {self.num_sample_per_chirp}')
        print(f'# of chirp/frame: {self.num_chirp_per_frame}')
        print(f'# of sample/frame: {self.num_sample_per_frame}')
        print(f'Size of one frame: {self.size_per_frame} Bytes')
        print(f'# of frames in the raw ADC data file: {self.num_frame}')
        print(f'Rx channels enabled: {bin(self.rx_chanl_enable)}')
        print(f'# of Rx channels: {self.num_rx_chnl}')
        print(f'Radar bandwidth: {self.bw / 1e3} (GHz)')
        print(f'ADC sampling rate: {self.adc_samp_rate} (MSa/s)')
        print(f'ADC bits: {self.adc_bits} bit')
        print(f'dBFS scaling factor: {self.dbfs_coeff} (dB)')
        print(f'Chirp duration: {self.chirp_idle_time + self.chirp_ramp_time} (usec)')
        print(f'Chirp slope: {self.chirp_slope} (MHz/usec)')
        print(f'Chirp bandwidth: {self.bw} (MHz)')
        print(f'Chirp "valid" duration: {self.num_sample_per_chirp / self.adc_samp_rate} (usec)')
        print(f'Frame length: {self.num_chirp_per_frame * (self.chirp_idle_time + self.chirp_ramp_time) / 1e3} (msec)')
        print(f'Frame periodicity: {self.frame_periodicity} (msec)')
        print(f'Frame duty-cycle: {self.num_chirp_per_frame * (self.chirp_idle_time + self.chirp_ramp_time) / 1e3 / self.frame_periodicity}')
        print(f'Range limit: {self.range_max:.4f} (m)')
        print(f'Range resolution: {self.range_res:.4f} (m)')
        print(f'Velocity limit: {self.v_max:.4f} (m/s)')
        print(f'Velocity resolution: {self.v_res:.4f} (m/s)')
        print(f'IQ swap?: {self.is_iq_swap}')
        print(f'Interleaved data?: {self.is_interleave}')
        print('...System configuration imported!')

def hex2poly(hex_string):
    hex_string = hex_string.replace('0x', '')
    num = int(hex_string, 16)
    return [int(x) for x in bin(num)[2:]]

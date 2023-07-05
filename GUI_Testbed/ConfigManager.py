import json
import os
import sys
import numpy as np
import scipy.constants as constants
from collections import OrderedDict

#invalid configuration exception
class InvalidConfiguration(Exception):
    pass

class ConfigNotLoaded(Exception):
    pass

class ConfigManager:

    def __init__(self):

        #path for the TI radar config file
        self.TI_radar_config_path = None
        
        #path for a JSON configuration file
        self.json_TI_radar_config_path = None
        
        #configuration information stored as a dict
        self.radar_config = OrderedDict()
        self.radar_performance = {}

        #status flags
        self.config_loaded = False

        return

#Computing radar performance

    def compute_radar_perforance(self):
        """Compute range and velocity performance specs and save in the self.radar_performance object
        """
        if self.config_loaded:
            self.radar_performance["range"] = self._compute_range_performance()
            self.radar_performance["velocity"] = self._compute_velocity_performance()
        else:
            raise ConfigNotLoaded("ConfigManager.compute_radar_performance: Attempted to compute performance specs, but no configuration was loaded")
    
    def _compute_range_performance(self):
        """Compute key range performance parameters

        Returns:
            dict: dictionary with num_range_bins,range_res,range_idx_to_m, and range_max
        """

        #declare empty dict to contain range performance information
        range_performance = {}

        #get required quantities to compute range performance
        ADC_freq_kHz = float(self.radar_config["profileCfg"]["sampleRate"])
        num_ADC_samples = float(self.radar_config["profileCfg"]["adcSamples"])
        num_range_bins = np.power(2,np.ceil(np.log2(num_ADC_samples)))
        chirp_slope_MHz_us = float(self.radar_config["profileCfg"]["freqSlope"])
        
        #num_range_bins
        range_performance["num_range_bins"] = num_range_bins

        #range resolution
        range_res = (constants.c * ADC_freq_kHz * 1e3)/ (2 * chirp_slope_MHz_us * (1e6/1e-6) * num_ADC_samples)
        range_performance["range_res"] = range_res

        #range IDX to meters
        range_idx_to_m = (constants.c * ADC_freq_kHz * 1e3)/ (2 * chirp_slope_MHz_us * (1e6/1e-6) * num_range_bins)
        range_performance["range_idx_to_m"] = range_idx_to_m

        #max range
        max_range = (constants.c * ADC_freq_kHz * 1e3) / (2 * chirp_slope_MHz_us * (1e6/1e-6))
        range_performance["range_max"] = max_range

        return range_performance
    
    def _compute_velocity_performance(self):
        """Compute key velociy performance parameters

        Returns:
            dict: dictionary with num_doppler_bins, vel_res, vel_idx_to_m_per_s, and vel_max
        """
        #declare empty dict to contain velocity performance information
        vel_performance = {}

        #get required quantities to compute velocity performance
        start_freq_GHz = float(self.radar_config["profileCfg"]["startFreq"])
        lambda_m = constants.c / (start_freq_GHz * 1e9)
        num_Tx_antennas = self._get_num_Tx_antennas()
        chirp_start_profile_idx = int(self.radar_config["frameCfg"]["startIndex"])
        chirp_end_profile_idx = int(self.radar_config["frameCfg"]["endIndex"])
        num_loops = float(self.radar_config["frameCfg"]["loops"])
        num_chirps_per_frame = int((chirp_end_profile_idx - chirp_start_profile_idx + 1) * num_loops)
        ramp_end_time_us = float(self.radar_config["profileCfg"]["rampEndTime"])
        idle_time_us = float(self.radar_config["profileCfg"]["idleTime"])
        chirp_period_us = ramp_end_time_us + idle_time_us

        #num_doppler_bins
        num_doppler_bins = num_chirps_per_frame / num_Tx_antennas
        vel_performance["num_doppler_bins"] = num_doppler_bins

        #velocity_resolution_m_per_s
        vel_res = lambda_m / (2 * chirp_period_us * 1e-6 * num_chirps_per_frame)
        vel_performance["vel_res"] = vel_res

        #vel_idx_to_m_per_s
        vel_performance["vel_idx_to_m_per_s"] = vel_res

        #max_velocity
        vel_max = lambda_m / (4 * chirp_period_us * 1e-6 * num_Tx_antennas)
        vel_performance["vel_max"] = vel_max

        return vel_performance
    
    def _get_num_Tx_antennas(self):
        """Return the number of Tx Antennas used in the configuration

        Returns:
            int: the number of Tx antennas
        """
        
        match int(self.radar_config["channelCfg"]["txChannelEn"]):
            case 1:
                return 1
            case 5:
                return 2
            case 7:
                return 3


#Importing from JSON
    def load_config_from_JSON(self,json_TI_radar_config_path:str):
        """Load a TI radar config from a JSON file

        Args:
            json_TI_radar_config_path (str): path to the JSON file
        """
        #open the JSON file
        f = open(json_TI_radar_config_path)
        content = ''
        for line in f:
            content += line
        self.radar_config = json.loads(content,object_pairs_hook=OrderedDict)

        self.config_loaded = True
        self.json_TI_radar_config_path = json_TI_radar_config_path

#exporting to .cfg
    def export_config_as_cfg(self,save_file_path:str):
        """Export the loaded radar config as a .cfg file, and set the exported path as the current .cfg path

        Args:
            save_file_path (str): path to save the configuration to
        """
        if self.config_loaded:
            out_string = 'sensorStop\nflushCfg\n'

            for key in self.radar_config:
                command_string = key
                params = self.radar_config[key]
                if key == "chirpCfg":
                    out_string += self._export_chirpCfg_config(params)
                else:
                    for param_key in params:
                        value = params[param_key]
                        if type(value) is list:
                            command_string += " " + " ".join(["{}".format(item) for item in value])
                        elif value != None:
                            command_string += " {}".format(value)
                    
                    #append to the out string
                    out_string += command_string + "\n"

            #append sensor start to the configuration
            out_string += "sensorStart"

            #save to the file
            f = open(save_file_path,"w")
            f.write(out_string)
            f.close()

            self.TI_radar_config_path = save_file_path
        else:
            ConfigNotLoaded("ConfigManager.export_config_as_cfg: No configuration loaded to save")
    
    def _export_chirpCfg_config(self,chirp_configs:list):
        """Special behavior to handle multiple chirp configurations

        Args:
            chirp_configs (list): a list of chirp configurations stored in dictionaries
        """
        out_str = ""
        for config in chirp_configs:
            command_string = "chirpCfg"
            for param_key in config:
                value = config[param_key]
                if type(value) is list:
                    command_string += " " + " ".join(["{}".format(item) for item in value])
                elif value != None:
                    command_string += " {}".format(value)
            out_str += command_string +"\n"
        
        return out_str

#exporting to .json
    def export_config_as_json(self,save_file_path:str):
        """Export the loaded TI radar configuration as a JSON file, and set the exported path as the current .json path

        Args:
            save_file_path (str): path to save the configuration to
        """
        if self.config_loaded:
            js = json.dumps(self.radar_config, sort_keys=False, indent=4, separators=(',', ': '))
            with open(save_file_path, 'w') as f:
                f.write(js)
            
            self.json_TI_radar_config_path = save_file_path
        else:
            ConfigNotLoaded("ConfigManager.export_config_as_json: No configuration loaded to save")

#import configuration from .cfg file
    def load_config_from_cfg(self,TI_radar_config_path:str):
        """Load a configuration from a .cfg file

        Args:
            TI_radar_config_path (str): path to the .cfg file
        """
        #open the .cfg file file
        f = open(TI_radar_config_path)
        #reset the radar config
        self.radar_config = OrderedDict()
        for line in f:
            self._load_cfg_command_from_line(line)
        
        self.TI_radar_config_path = TI_radar_config_path
        self.config_loaded = True
    
    def _load_cfg_command_from_line(self,line:str):
        
        #split the line in parts
        str_split = line.strip("\n").split(" ")
        key = str_split[0]

        match key:
            case "dfeDataOutputMode":
                self._load_dfeDataOutputMode_from_cfg(str_split)
            case "channelCfg":
                self._load_channelCfg_from_cfg(str_split)
            case "adcCfg":
                self._load_adcCfg_from_cfg(str_split)
            case "adcbufCfg":
                self._load_adcbufCfg_from_cfg(str_split)
            case "profileCfg":
                self._load_profileCfg_from_cfg(str_split)
            case "chirpCfg":
                self._load_chirpCfg_from_cfg(str_split)
            case "frameCfg":
                self._load_frameCfg_from_cfg(str_split)
            case "lowPower":
                self._load_lowPower_from_cfg(str_split)
            case "guiMonitor":
                self._load_guiMonitor_from_cfg(str_split)
            case "cfarCfg":
                self._load_cfarCfg_from_cfg(str_split)
            case "peakGrouping":
                self._load_peakGrouping_from_cfg(str_split)
            case "multiObjBeamForming":
                self._load_multiObjBeamForming_from_cfg(str_split)
            case "clutterRemoval":
                self._load_clutterRemoval_from_cfg(str_split)
            case "calibDcRangeSig":
                self._load_calibDcRangeSig_from_cfg(str_split)
            case "compRangeBiasAndRxChanPhase":
                self._load_compRangeBiasAndRxChanPhase_from_cfg(str_split)
            case "measureRangeBiasAndRxChanPhase":
                self._load_measureRangeBiasAndRxChanPhase_from_cfg(str_split)
            case "CQRxSatMonitor":
                self._load_CQRxSatMonitor_from_cfg(str_split)
            case "CQSigImgMonitor":
                self._load_CQSigImgMonitor_from_cfg(str_split)
            case "analogMonitor":
                self._load_analogMonitor_from_cfg(str_split)
            case _:
                if key not in ["sensorStop","flushCfg","sensorStart"]:
                    raise InvalidConfiguration("Received unknown configuration command")
        

    def _load_dfeDataOutputMode_from_cfg(self,params:list):
        self.radar_config["dfeDataOutputMode"] = {
            "modeType":params[1]
        }

    def _load_channelCfg_from_cfg(self,params:list):
        self.radar_config["channelCfg"] = {
            "rxChannelEn": params[1],
            "txChannelEn": params[2],
            "cascading": params[3]
        }
        

    def _load_adcCfg_from_cfg(self,params:list):
        
        self.radar_config["adcCfg"] = {
            "numADCBits": params[1],
            "adcOutputFmt": params[2]
        }

    def _load_adcbufCfg_from_cfg(self,params:list):
        self.radar_config["adcbufCfg"] = {
            "subFrameIdx": None,
            "adcOutputFmt": params[1],
            "SampleSwap": params[2],
            "ChannelInterleave": params[3],
            "chirpThreshold": params[4]
        }

    def _load_profileCfg_from_cfg(self,params:list):
        self.radar_config["profileCfg"] = {
            "profileId": params[1],
            "startFreq": params[2],
            "idleTime": params[3],
            "adcStartTime": params[4],
            "rampEndTime": params[5],
            "txOutPower": params[6],
            "txPhaseShifter": params[7],
            "freqSlope": params[8],
            "txStartTime": params[9],
            "adcSamples": params[10],
            "sampleRate": params[11],
            "hpfCornerFreq1": params[12],
            "hpfCornerFreq2": params[13],
            "rxGain": params[14]
        }

    def _load_chirpCfg_from_cfg(self,params:list):
        
        value = {
            "startIndex": params[1],
            "endIndex": params[2],
            "profile": params[3],
            "startFreqVariation":params[4],
            "freqSlopVariation":params[5],
            "idleTimeVariation":params[6],
            "ADCStartTimeVariation":params[7],
            "txMask": params[8]
        }
        
        if "chirpCfg" in self.radar_config.keys():
            self.radar_config["chirpCfg"].append(value)
        else:
            self.radar_config["chirpCfg"] = [value]
        

    def _load_frameCfg_from_cfg(self,params:list):
        self.radar_config["frameCfg"] = {
            "startIndex": params[1],
            "endIndex": params[2],
            "loops": params[3],
            "frames": params[4],
            "periodicity": params[5],
            "trigger": params[6],
            "triggerDelay": params[7]
        }
        

    def _load_lowPower_from_cfg(self,params:list):
        self.radar_config["lowPower"] = {
            "chain": params[1],
            "adcMode": params[2]
        }

    def _load_guiMonitor_from_cfg(self,params:list):
        self.radar_config["guiMonitor"] = {
            "subFrameIndex": None,
            "detectedObjects": params[1],
            "rangeProfile": params[2],
            "noiseProfile": params[3],
            "rangeAzimuthHeatMap": params[4],
            "rangeDopplerHeatMap": params[5],
            "statsInfo": params[6]
        }

    def _load_cfarCfg_from_cfg(self,params:list):
        self.radar_config["cfarCfg"] = {
            "subFrameIndex": None,
            "direction": params[1],
            "mode": params[2],
            "noiseWindow": params[3],
            "guardLength": params[4],
            "shiftDivisor": params[5],
            "cyclic": params[6],
            "threshold": params[7]
        }

    def _load_peakGrouping_from_cfg(self,params:list):
        self.radar_config["peakGrouping"] = {
            "subFrameIndex": None,
            "scheme": params[1],
            "range": params[2],
            "doppler": params[3],
            "startRangeIndex": params[4],
            "endRangeIndex": params[5]
        }
        

    def _load_multiObjBeamForming_from_cfg(self,params:list):
        self.radar_config["multiObjBeamForming"] = {
            "subFrameIndex": None,
            "FeatureEnabled": params[1],
            "threshold": params[2]
        }

    def _load_clutterRemoval_from_cfg(self,params:list):
        self.radar_config["clutterRemoval"] = {
            "enabled":params[1]
        }

    def _load_calibDcRangeSig_from_cfg(self,params:list):
        self.radar_config["calibDcRangeSig"] = {
            "subFrameIndex": None,
            "enabled": params[1],
            "negativeBinIndex": params[2],
            "positiveBinIndex": params[3],
            "chirps": params[4]
        }
   
    def _load_compRangeBiasAndRxChanPhase_from_cfg(self,params:list):
        self.radar_config["compRangeBiasAndRxChanPhase"] = {
            "rangeBias": None,
            "phaseBias": params[1:]
        }
        

    def _load_measureRangeBiasAndRxChanPhase_from_cfg(self,params:list):
        self.radar_config["measureRangeBiasAndRxChanPhase"] = {
            "enabled": params[1],
            "targetDistance": params[2],
            "searchWindow": params[3]
        }

    def _load_CQRxSatMonitor_from_cfg(self,params:list):
        self.radar_config["CQRxSatMonitor"] = {
            "profile":params[1],
            "satMonSel":params[2],
            "priSliceDuration":params[3],
            "numSlices":params[4],
            "rxChanMask":params[5]
        }

    def _load_CQSigImgMonitor_from_cfg(self,params:list):
        self.radar_config["CQSigImgMonitor"] = {
            "profile":params[1],
            "numSlices":params[2],
            "numSamplesPerSlice":params[3]
        }
    
    def _load_analogMonitor_from_cfg(self,params:list):
        self.radar_config["analogMonitor"] = {
            "rxSaturation": params[1],
            "sigImgBand": params[2]
        }
    
if __name__ == '__main__':
    #create the controller object
    dir_path = os.path.dirname(os.path.realpath(__file__))
    os.chdir(dir_path)
    cfg_manager = ConfigManager()
    cfg_manager.load_config_from_cfg("../configurations/1443config.cfg")
    #cfg_manager.load_config_from_JSON("../configurations/jsonconfig.json")
    cfg_manager.compute_radar_perforance()
    cfg_manager.export_config_as_cfg("../configurations/generated_config.cfg")
    cfg_manager.export_config_as_json("../configurations/generated_config.json")
    #Exit the python code
    sys.exit()
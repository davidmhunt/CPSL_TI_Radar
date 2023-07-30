from multiprocessing.connection import Connection
from multiprocessing import connection,AuthenticationError

from collections import OrderedDict
import time
import json
import numpy as np
import os
import sys

#plotting
import matplotlib.pyplot as plt

from CPSL_TI_Radar._Background_Process import _BackgroundProcess
from CPSL_TI_Radar._Message import _Message,_MessageTypes
from CPSL_TI_Radar.Processors._TLVProcessor_PointCloud import DetectedPointsProcessor

class TLVTags:
    DETECTED_POINTS = 1
    RANGE_PROFILE = 2
    NOISE_PROFILE=3
    AZIMUTH_STATIC_HEAT_MAP=4
    RANGE_DOPPLER_HEAT_MAP=5
    STATS=6
    

class Processor(_BackgroundProcess):
    def __init__(self,
                 conn:Connection,
                 data_connection:Connection,
                 config_file_path='config_Radar.json'):
        
        super().__init__(process_name="Processor",
                         conn=conn,
                         config_file_path=config_file_path,
                         data_connection=data_connection)
        
        
        #radar performance specs for the given config
        self.config_loaded = False
        self.radar_performance = {}
        self.radar_config = OrderedDict()
        
        #buffers for processing packets
        self.current_packet = bytearray()
        self.magic_word = bytearray([0x02,0x01,0x04,0x03,0x06,0x05,0x08,0x07])
        self.header = {}

        #import tlv processor classes
        self.enable_plotting = False
        self.save_plots_as_gifs = False
        self.tlv_processor_detected_objects = None

        self._init_TLV_processes()
        
        #initialize the streaming status
        self.streaming_enabled = False

        #set the verbose status
        self.verbose = self.config_Radar["Processor"]["verbose"]

        self._conn_send_init_status(self.init_success)
        self.run()

        return
    
    def run(self):
        try:
            while self.exit_called == False:
                #process new messages from either the Radar or the 
                if self.streaming_enabled:
                    #wait until either the Radar or the Processor sends data
                    ready_conns = connection.wait([self._conn_RADAR,self._conn_data],timeout=None)
                    for conn in ready_conns:
                        if conn == self._conn_RADAR:
                            self._conn_process_Radar_command()
                        else: #must be new data available
                            self._process_new_packet()
                else:
                    self._conn_process_Radar_command()

            self.close()
        except KeyboardInterrupt:
            self.close()
            sys.exit()
        
        return
    
    def close(self):
        """End Processor Operations (no custom behavior requred)
        """
        #save gifts to files if they were enabled
        self.tlv_processor_detected_objects.save_gif_to_file()
        return

#configure TLV processors
    def _init_TLV_processes(self):

        #import tlv processor classes
        self.enable_plotting = self.config_Radar["Processor"]["enable_plotting"]
        self.save_plots_as_gifs = self.config_Radar["Processor"]["save_plots_as_gif"]
        
        self.tlv_processor_detected_objects = DetectedPointsProcessor(
            plotting_enabled=self.enable_plotting,
            save_as_gif=self.save_plots_as_gifs)
    
    def _init_TLV_listeners(self):

        #get the TLV client initialization information
        TLV_listener_info = self.config_Radar["Processor"]["TLV_listener_info"]
        
        #generate the authentication string
        authkey_str = TLV_listener_info["authkey"]
        authkey = authkey_str.encode()

        #get the TLV client addresses
        detected_points_address = ('localhost', int(TLV_listener_info["DetectedPointsProcessor"]))

        #wait for the TLV clients to connect to their listeners
        try:
            self.tlv_processor_detected_objects.init_conn_client(detected_points_address,authkey)
        except AuthenticationError:
            self._conn_send_message_to_print("Processor._init_TLV_listeners: experienced Authentication error when attempting to connect to Client")
            self._conn_send_error_radar_message()


#processing packets
    def _process_new_packet(self):
        
        #receive the latest packet from the processor
        while self._conn_data.poll():
            try:
                self.current_packet = self._conn_data.recv_bytes()
            except EOFError:
                self._conn_send_message_to_print("Processor._process_new_packet: attempted to receive new packet from Streamer, but streamer was closed")
                self._conn_send_error_radar_message()
                return

        self._process_header()

        self._process_TLVs()

        return
    
    def _process_header(self):

        #decode the header
        decoded_header = np.frombuffer(self.current_packet[:36],dtype=np.uint32)
        #process the header fields
        self.header["version"] = format(decoded_header[2],'x')
        self.header["packet_length"] = decoded_header[3]
        self.header["platform"] = format(decoded_header[4],'x')
        self.header["frame_number"] = decoded_header[5]
        self.header["time"] = decoded_header[6]
        self.header["num_detected_objects"] = decoded_header[7]
        self.header["num_data_structures"] = decoded_header[8]

        return
    
    def _process_TLVs(self):

        #first index is after the start of the packet
        idx = 36
        for i in range(self.header["num_data_structures"]):
            TLV_info = np.frombuffer(self.current_packet[idx:idx+8],dtype=np.uint32)
            TLV_tag = TLV_info[0]
            TLV_length = TLV_info[1]
            
            #process the TLV data
            self._process_TLV(TLV_tag,self.current_packet[idx:idx+TLV_length + 8])

            #increment the index
            idx += TLV_length + 8
        
        return
    def _process_TLV(self,TLV_tag,data:bytearray):

        #call the correct function to process to given TLV data
        try:
            match TLV_tag:
                case TLVTags.DETECTED_POINTS:
                    self.tlv_processor_detected_objects.process_new_data(data)
        except BrokenPipeError:
            self._conn_send_message_to_print("Processor._process_TLV: attempted to send data to Listener, but Client process was already closed")
            self._conn_send_error_radar_message()

#Loading new radar configurations
    def _load_new_config(self, config_info:dict):
        """Load a new set of radar performance and radar configuration dictionaries into the processor class

        Args:
            config_info (dict): Dictionary with entries for "radar_config" and "radar_performance"
        """
        #load a new set of radar performance specs and radar configuration dictionaries into the processor class
        self.radar_config=config_info["radar_config"]
        self.radar_performance=config_info["radar_performance"]

        #set config loaded flag
        self.config_loaded = True

        #TODO: Update this to support other TLV types
        self.tlv_processor_detected_objects.load_config(
            radar_performance= self.radar_performance,
            radar_config=self.radar_config)

#Streaming/processing of radar samples
    def _start_streaming(self):
        """sets the streaming_enabled flag to true. Checks to make sure that a configuration is loaded first
        """
        if self.config_loaded == False:
            self._conn_send_message_to_print("Processor._start_streaming: Attempted to start streaming without loading a configuration first")
            self._conn_send_error_radar_message()
        else:
            self.streaming_enabled = True
        
        return
    
    def _conn_process_Radar_command(self):
        """Wait for and then execute commands from the Radar class. Sends the command type back to the Radar as confirmation that the command has been performed
        """
        
        command:_Message = self._conn_RADAR.recv()
        match command.type:
            case _MessageTypes.EXIT:
                self.exit_called = True
            case _MessageTypes.LOAD_NEW_CONFIG:
                self._load_new_config(command.value)
            case _MessageTypes.START_STREAMING:
                self._start_streaming()
            case _MessageTypes.STOP_STREAMING:
                self.streaming_enabled = False
            case _MessageTypes.CONFIG_TLV_LISTENERS:
                self._init_TLV_listeners()
                self._conn_send_command_executed_message(_MessageTypes.CONFIG_TLV_LISTENERS)
            case _:
                self._conn_send_message_to_print(
                    "Processor._process_Radar_command: command not recognized")
                self._conn_send_error_radar_message()
            
        self._conn_send_command_executed_message(command.type)
        
        return

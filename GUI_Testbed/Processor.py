from multiprocessing.connection import Connection
from multiprocessing import connection
from _Message import _Message,_MessageTypes
from collections import OrderedDict
import time
import json
import numpy as np
import os
import sys

from _Background_Process import _BackgroundProcess

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

        #initialize the streaming status
        self.streaming_enabled = False

        #set the verbose status
        self.verboses = self.config_Radar["Processor"]["verbose"]

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
        pass

#processing packets
    def _process_new_packet(self):
        
        #receive the latest packet from the processor
        while self._conn_data.poll():
            self._conn_data.recv_bytes_into(self.current_packet)

        #TODO: Add code to process the packet
        self._process_header()

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
            case _:
                self._conn_send_message_to_print(
                    "Processor._process_Radar_command: command not recognized")
                self._conn_send_error_radar_message()
            
        self._conn_send_command_executed_message(command.type)
        
        return

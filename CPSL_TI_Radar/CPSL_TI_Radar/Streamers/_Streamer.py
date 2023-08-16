import serial
import time
import json
import numpy as np
import os
import sys
from collections import OrderedDict
from multiprocessing.connection import Connection

#helper classes
from CPSL_TI_Radar._Background_Process import _BackgroundProcess
from CPSL_TI_Radar._Message import _Message,_MessageTypes

class _Streamer(_BackgroundProcess):

    def __init__(self,
                 conn_parent:Connection,
                 conn_processor_data:Connection, 
                 conn_handler_data:Connection = None,
                 settings_file_path='config_Radar.json'):
        """Initialize the parent Streamer class

        Args:
            conn_parent (Connection): connection to the Radar class
            conn_processor_data (Connection): connection to the Processor Class
            conn_handler_data (Connection, optional): connection to a Handler Class (in event of DCA1000).
                Defaults to None
            settings_file_path (str, optional): Path to the radar settings json file. Defaults to 'config_Radar.json'.
        """

        super().__init__(
            process_name="Streamer",
            conn_parent=conn_parent,
            conn_processor_data=conn_processor_data,
            conn_handler_data=conn_handler_data,
            settings_file_path=settings_file_path
        )

        #parameters to store radar configuration
        self.config_loaded = False
        self.radar_performance = {}
        self.radar_config = OrderedDict()
        
        #storing data
        self.current_packet = bytearray()
        self.byte_buffer = bytearray()

        #initialize the streaming status
        self.streaming_enabled = False

        #set verbose status
        self.verbose = self._settings["Streamer"]["verbose"]

        return

    def run(self):
        try:
            while self.exit_called == False:
                #if streaming enabled, minimize blocking/waiting
                if self.streaming_enabled:
                    self._get_next_frame_packet()
                    #process new RADAR commands if availble
                    if self._conn_parent.poll():
                        #process all radar commands
                        while self._conn_parent.poll():
                            #receive and process the message from the RADAR class
                            self._conn_process_Radar_command()
                else:
                    self._conn_process_Radar_command()


            #once exit is called close out and return
            self.close()
        except KeyboardInterrupt:
            self.close()
            sys.exit()
    
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

        return
    
    def close(self):
        #implemented by child
        pass
       
    def _get_next_frame_packet(self):

        #must be implemented in child class
        pass

    def _start_streaming(self):
        
        #implemented in the child class
        #function must set self.streaming_enabled
        pass

    def _stop_streaming(self):

        #implemented in child class
        #function must set self.streaming_enabled
        pass
            
            
    
    def _conn_process_Radar_command(self):

        command:_Message = self._conn_parent.recv()
        match command.type:
            case _MessageTypes.EXIT:
                self.exit_called = True
            case _MessageTypes.START_STREAMING:
                self._start_streaming()
            case _MessageTypes.STOP_STREAMING:
                self._stop_streaming()
            case _MessageTypes.LOAD_NEW_CONFIG:
                self._load_new_config(command.value)
            case _:
                self._conn_send_message_to_print(
                    "Streamer._process_Radar_command: command not recognized")
                self._conn_send_parent_error_message()
        
        self._conn_send_command_executed_message(command.type)
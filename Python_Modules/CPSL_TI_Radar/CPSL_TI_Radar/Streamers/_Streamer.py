import serial
import time
import json
import numpy as np
import os
import sys
from multiprocessing.connection import Connection

#helper classes
from CPSL_TI_Radar._Background_Process import _BackgroundProcess
from CPSL_TI_Radar._Message import _Message,_MessageTypes

class _Streamer(_BackgroundProcess):

    def __init__(self,
                 conn:Connection,
                 data_connection:Connection, 
                 config_file_path='config_Radar.json'):

        super().__init__("Streamer",conn,config_file_path,data_connection)

        #initialize the streaming status
        self.streaming_enabled = False

        #set verbose status
        self.verbose = self.config_Radar["Streamer"]["verbose"]

        return

    def run(self):
        try:
            while self.exit_called == False:
                #if streaming enabled, minimize blocking/waiting
                if self.streaming_enabled:
                    self._get_next_frame_packet()
                    #process new RADAR commands if availble
                    if self._conn_RADAR.poll():
                        #process all radar commands
                        while self._conn_RADAR.poll():
                            #receive and process the message from the RADAR class
                            self._conn_process_Radar_command()
                else:
                    self._conn_process_Radar_command()


            #once exit is called close out and return
            self.close()
        except KeyboardInterrupt:
            self.close()
            sys.exit()
    
    def close(self):
        #implemented by child
        pass
       
    def _get_next_frame_packet(self):

        #must be implemented in child class
        pass
            
            
    
    def _conn_process_Radar_command(self):

        command:_Message = self._conn_RADAR.recv()
        match command.type:
            case _MessageTypes.EXIT:
                self.exit_called = True
            case _MessageTypes.START_STREAMING:
                self.serial_port.open()
                self._serial_reset_packet_detector()
                self.streaming_enabled = True
            case _MessageTypes.STOP_STREAMING:
                self.serial_port.close()
                self.streaming_enabled = False
            case _:
                self._conn_send_message_to_print(
                    "Streamer._process_Radar_command: command not recognized")
                self._conn_send_error_radar_message()
        
        self._conn_send_command_executed_message(command.type)
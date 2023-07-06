import serial
import time
import json
import numpy as np
import os
import sys

#helper classes
from _Background_Process import _BackgroundProcess
from multiprocessing.connection import Connection
from _Message import _Message,_MessageTypes

class Streamer(_BackgroundProcess):

    def __init__(self,
                 conn:Connection,
                 data_connection:Connection, 
                 config_file_path='config_Radar.json'):

        super().__init__("Streamer",conn,config_file_path,data_connection)

        #configure the streaming method
        self.serial_streaming_enabled = False
        self.file_streaming_enabled = False
        self.data_file_path = ""
        self._config_streaming_method()
        
        #initialize the packet detector
        self.detected_packets = 0
        self.current_packet = bytearray()
        self.byte_buffer = bytearray()
        self.magic_word = bytearray([0x02,0x01,0x04,0x03,0x06,0x05,0x08,0x07])
        self.header = {}

        #initialize the streaming status
        self.streaming_enabled = False

        #set verbose status
        self.verbose = self.config_Radar["Streamer"]["verbose"]

        self._conn_send_init_status(self.init_success)
        self.run()

        return

    def run(self):
        try:
            while self.exit_called == False:
                #if streaming enabled, minimize blocking/waiting
                if self.streaming_enabled:
                    self._serial_get_next_packet()
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
        #before exiting, close the serial port and turn the sensor off
        if self.serial_port.is_open == True:
            #close the serial port
            self.serial_port.close()
    
    
    def _config_streaming_method(self):
        
        #determine which streaming methods are enabled
        self.serial_streaming_enabled = self.config_Radar["Streamer"]["serial_streaming"]["enabled"]
        self.file_streaming_enabled = self.config_Radar["Streamer"]["file_streaming"]["enabled"]

        #configure the serial port if serial streaming is enabled
        if self.serial_streaming_enabled:
            self._serial_init_serial_port(
                address=self.config_Radar["Streamer"]["serial_streaming"]["data_port"],
                baud_rate=921600,
                timeout=0.5,
                close=True
            )
        elif self.file_streaming_enabled:
            self.data_file_path = self.config_Radar["Streamer"]["file_streaming"]["data_file"]
    
    def _serial_get_next_packet(self):

        #read the new packet (strip off the magic word)
        try:
            self.byte_buffer = self.serial_port.read_until(expected=self.magic_word)[:-8]
        except serial.SerialTimeoutException:
            self._conn_send_message_to_print(
                "Streamer._get_next_packet_serial: Timed out waiting for new data. serial port closed")
            self._conn_send_error_radar_message()
            self.serial_port.close()
            self.streaming_enabled = False
            return
        
        #store the new packet in a bytearray
        self.current_packet = bytearray(self.magic_word)
        self.current_packet.extend(self.byte_buffer)

        #increment the packet count
        self.detected_packets += 1
        
        #decode the header
        self._serial_decode_header(self.current_packet[:36])

        #check packet validity
        packet_valid = self._serial_check_packet_valid()

        if packet_valid:
            self._conn_data.send_bytes(self.current_packet)
        
        return
            
            
    def _serial_decode_header(self,header:bytearray):
        #decode the header
        decoded_header = np.frombuffer(header,dtype=np.uint32)
        #process the header fields
        self.header["version"] = format(decoded_header[2],'x')
        self.header["packet_length"] = decoded_header[3]
        self.header["platform"] = format(decoded_header[4],'x')
        self.header["frame_number"] = decoded_header[5]
        self.header["time"] = decoded_header[6]
        self.header["num_detected_objects"] = decoded_header[7]
        self.header["num_data_structures"] = decoded_header[8]

        if(self.verbose):
            self._serial_print_packet_header()

        return
    
    def _serial_print_packet_header(self):
        #clear the terminal screen
        self._conn_send_clear_terminal()

        #print out the packet detection results
        self._conn_send_message_to_print("detected packets: {}".format(self.detected_packets))
        self._conn_send_message_to_print("\t version:{}".format(self.header["version"]))
        self._conn_send_message_to_print("\t total packet length:{}".format(self.header["packet_length"]))
        self._conn_send_message_to_print("\t platform:{}".format(self.header["platform"]))
        self._conn_send_message_to_print("\t Frame Number:{}".format(self.header["frame_number"]))
        self._conn_send_message_to_print("\t Time (CPU Cycles):{}".format(self.header["time"]))
        self._conn_send_message_to_print("\t Number of Detected Objects:{}".format(self.header["num_detected_objects"]))
        self._conn_send_message_to_print("\t Number of Data Structures in package:{}".format(self.header["num_data_structures"]))

        return
    
    def _serial_check_packet_valid(self):
        """Check to see if the current packet is valid. Assumes that the current packet is loaded into self.current_packet and that the corresponding header has been processed and loaded into self.header

        Returns:
            bool: True if packet is valid, False if packet is not valid
        """
        packet_valid = False
        if self.header["packet_length"] == len(self.current_packet):
            packet_valid = True
        else:
            packet_valid = False
        
        if self.verbose:
            self._conn_send_message_to_print("\t Valid Packet: {}".format(packet_valid))
        return packet_valid
    
    def _serial_reset_packet_detector(self):

        #flush the input buffer
        self.serial_port.reset_input_buffer()
        
        #find the first magic word in the buffer
        #NOTE: the first packet received is not likely to be complete,
        #and is thus thrown out
        self.serial_port.read_until(expected=self.magic_word)

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
import serial
import time
import json
import numpy as np
import os
import sys

class Streamer:

    def __init__(self, config_file_path='config_Streamer.json'):

        #read the Streamer JSON configuration file
        try:
            self.config_Streamer = self._ParseJSON(config_file_path)
        except FileNotFoundError:
            print("Streamer.__init__: could not find {} in {}".format(config_file_path,os.getcwd()))
            return

        #configure the streaming method
        self.serial_streaming_enabled = False
        self.serial_port = None
        self.file_streaming_enabled = False
        self.data_file_path = ""
        self._ConfigStreamingMethod()
        
        #initialize the packet detector
        self.detected_packets = 0
        self.current_packet = bytearray()
        self.magic_word = bytearray([0x02,0x01,0x04,0x03,0x06,0x05,0x08,0x07])
        self.header = {}

        #initialize the streaming status
        self.streaming_enabled = True

        #set verbose status
        self.verbose = self.config_Streamer["verbose"]

        return

    def _DetectPackets_serial(self):
        
        #find the first magic word in the buffer
        self.serial_port.read_until(expected=self.magic_word)

        #continuously stream and detect packets
        byte_buffer = bytearray()
        while(self.streaming_enabled):
            #read the new packet (strip off the magic word)
            byte_buffer = self.serial_port.read_until(expected=self.magic_word)[:-8]
            #TODO: make sure that I'm taking off the correct amount of the packet (only the magic word at the end)

            #store the new packet in a bytearray
            self.current_packet = bytearray(self.magic_word)
            self.current_packet.extend(byte_buffer)

            #increment the packet count
            self.detected_packets += 1
            
            #decode the header
            self._DecodeHeader(self.current_packet[:36])

            #check packet validity
            packet_valid = self._CheckPacketValid()
            



            
    def _DecodeHeader(self,header:bytearray):
        #TODO: add in capability to handle bad packets and a time-out
        try:
            decoded_header = np.frombuffer(header,dtype=np.uint32)

        except serial.SerialTimeoutException:
            print("Streamer._DecodeHeader: Timed out waiting for new data")
            return

        #process the header fields
        self.header["version"] = format(decoded_header[2],'x')
        self.header["packet_length"] = decoded_header[3]
        self.header["platform"] = format(decoded_header[4],'x')
        self.header["frame_number"] = decoded_header[5]
        self.header["time"] = decoded_header[6]
        self.header["num_detected_objects"] = decoded_header[7]
        self.header["num_data_structures"] = decoded_header[8]

        if(self.verbose):
            self._PrintHeader()

        return
    
    def _PrintHeader(self):
        #clear the terminal screen
        os.system('cls' if os.name == 'nt' else 'clear')

        #print out the packet detection results
        print("detected packets: {}".format(self.detected_packets))
        print("\t version:{}".format(self.header["version"]))
        print("\t total packet length:{}".format(self.header["packet_length"]))
        print("\t platform:{}".format(self.header["platform"]))
        print("\t Frame Number:{}".format(self.header["frame_number"]))
        print("\t Time (CPU Cycles):{}".format(self.header["time"]))
        print("\t Number of Detected Objects:{}".format(self.header["num_detected_objects"]))
        print("\t Number of Data Structures in package:{}".format(self.header["num_data_structures"]))

        return
    
    def _CheckPacketValid(self):
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
            print("\t Valid Packet: {}".format(packet_valid))
        return packet_valid
    
    def _ConfigStreamingMethod(self):
        
        #determine which streaming methods are enabled
        self.serial_streaming_enabled = self.config_Streamer["serial_streaming"]["enabled"]
        self.file_streaming_enabled = self.config_Streamer["file_streaming"]["enabled"]

        #configure the serial port if serial streaming is enabled
        if self.serial_streaming_enabled:
            self.serial_port = serial.Serial(self.config_Streamer["serial_streaming"]["data_port"],baudrate=921600,timeout=15)
        elif self.file_streaming_enabled:
            self.data_file_path = self.config_Streamer["file_streaming"]["data_file"]

    
    def _ParseJSON(self,json_file_path):
        """Read a json file at the given path and return a json object

        Args:
            json_file_path (str): path to the JSON file

        Returns:
            _type_: json
        """
        
        #open the JSON file
        f = open(json_file_path)
        content = ''
        for line in f:
            content += line
        return json.loads(content)

if __name__ == '__main__':
    #create the controller object
    dir_path = os.path.dirname(os.path.realpath(__file__))
    os.chdir(dir_path)
    streamer = Streamer()
    streamer._DetectPackets_serial()
    #Exit the python code
    sys.exit()
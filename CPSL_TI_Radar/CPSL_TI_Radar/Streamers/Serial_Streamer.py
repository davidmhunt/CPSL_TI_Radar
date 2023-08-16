import serial
import numpy as np
import sys

#helper classes
from multiprocessing.connection import Connection
from CPSL_TI_Radar._Message import _Message,_MessageTypes
from CPSL_TI_Radar.Streamers._Streamer import _Streamer

class SerialStreamer(_Streamer):

    def __init__(self,
                 conn_parent: Connection,
                 conn_processor_data: Connection,
                 conn_handler_data: Connection = None,
                 settings_file_path = 'config_Radar.json'):
        """Initialize the Serial Streamer class

        Args:
            conn_parent (Connection): connection to the Radar class
            conn_processor_data (Connection): connection to the Processor Class
            conn_handler_data (Connection, optional): connection to a Handler Class (in event of DCA1000).
                UNUSED FOR SERIAL STREAMER. Defaults to None
            settings_file_path (str, optional): Path to the radar settings json file. Defaults to 'config_Radar.json'.
        """

        super().__init__(
            conn_parent=conn_parent,
            conn_processor_data=conn_processor_data,
            conn_handler_data=conn_handler_data,
            settings_file_path=settings_file_path
        )
                
        #configure serial streaming
        self._config_serial_streaming()
        
        #initialize the serial packet detector
        self.detected_packets = 0
        self.magic_word = bytearray([0x02,0x01,0x04,0x03,0x06,0x05,0x08,0x07])
        self.header = {}

        self._conn_send_init_status(self.init_success)
        self.run()

        return
    
    def close(self):
        #before exiting, close the serial port and turn the sensor off
        if self.serial_port != None:
            if self.serial_port.is_open == True:
                #close the serial port
                self.serial_port.close()
    
    
    def _config_serial_streaming(self):
        """Configure the serial port for streaming the data
        """
        self._serial_init_serial_port(
                address=self._settings["Streamer"]["serial_streaming"]["data_port"],
                baud_rate=921600,
                timeout=0.5,
                close=True
            )
    
    
    def _get_next_frame_packet(self):

        #read the new packet (strip off the magic word)
        try:
            self.byte_buffer = self.serial_port.read_until(expected=self.magic_word)[:-8]
        except serial.SerialTimeoutException:
            self._conn_send_message_to_print(
                "Streamer._get_next_packet_serial: Timed out waiting for new data. serial port closed")
            self._conn_send_parent_error_message()
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
            try:
                self._conn_processor_data.send_bytes(self.current_packet)
            except BrokenPipeError:
                self._conn_send_message_to_print("SerialStreamer._serial_get_next_packet: attempted to send new packet to Processor, but processor was closed")
                self._conn_send_parent_error_message()
        
        return
            
    def _start_streaming(self):
        
        self.serial_port.open()
        self._serial_reset_packet_detector()
        self.streaming_enabled = True
    
    def _stop_streaming(self):

        self.serial_port.close()
        self.streaming_enabled = False

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

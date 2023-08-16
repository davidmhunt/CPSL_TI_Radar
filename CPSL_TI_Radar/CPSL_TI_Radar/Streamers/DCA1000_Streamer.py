import socket
import numpy as np
import sys
import struct

#helper classes
from multiprocessing.connection import Connection
from multiprocessing import Process,Pipe
from CPSL_TI_Radar._Message import _Message,_MessageTypes
from CPSL_TI_Radar.Streamers._Streamer import _Streamer
from CPSL_TI_Radar.Streamers.Handlers.DCA1000 import DCA1000Handler

class DCA1000Streamer(_Streamer):

    def __init__(self,
                 conn_parent: Connection,
                 conn_processor_data: Connection,
                 conn_handler_data: Connection,
                 settings_file_path = 'config_Radar.json'):
        """Initialize the DCA1000 Streamer class

        Args:
            conn_parent (Connection): connection to the Radar class
            conn_processor_data (Connection): connection to the Processor Class
            conn_handler_data (Connection, optional): connection to a Handler Class (in event of DCA1000).
                Defaults to None
            settings_file_path (str, optional): Path to the radar settings json file. Defaults to 'config_Radar.json'.
        """
        
        super().__init__(
            conn_parent = conn_parent,
            conn_processor_data = conn_processor_data,
            conn_handler_data=conn_handler_data,
            settings_file_path=settings_file_path
        )
        
        #packet handling
        self.udp_packet_num = 0
        self.udp_byte_count = 0
        self.dropped_udp_packets = 0

        #radar frame detection
        self.num_detected_frames = 0
        self.num_bytes_per_frame = 0

        self._conn_send_init_status(self.init_success)
        self.run()
        
        return

    
#loading new configurations
    def _load_new_config(self, config_info: dict):
        """Over-rided version of _load_new_config to do additional processing for the DCA1000. Load a new set of radar performance and radar configuration dictionaries into the processor class

        Args:
            config_info (dict): Dictionary with entries for "radar_config" and "radar_performance"
        """
        
        super()._load_new_config(config_info)

        num_bytes_per_int = 2
        num_ints_per_complex = 2
        num_LVDS_lanes = 4 #hard coded for IWR1443 on DCA1000

        samples_per_chirp = int(self.radar_config["profileCfg"]["adcSamples"])

        chirps_per_loop = int(self.radar_config["frameCfg"]["endIndex"]) - int(self.radar_config["frameCfg"]["startIndex"]) + 1

        loops_per_frame = int(self.radar_config["frameCfg"]["loops"])

        self.num_bytes_per_frame = num_bytes_per_int * num_ints_per_complex * num_LVDS_lanes * samples_per_chirp * chirps_per_loop * loops_per_frame
    
    def close(self):
        """End the streamer process
        """

        return

#start and stop streaming
    def _start_streaming(self):
        """Start streaming on DCA1000
        """
        
        self.streaming_enabled = True
    
    def _stop_streaming(self):
        """Stop Streaming on DCA1000
        """

        self.streaming_enabled = False

#process new packets
    def _get_next_frame_packet(self):
        """Get the next UDP packet and send to the processor
        """
        
        #get the next packet of data from the DCA1000
        try:
            msg = self._conn_handler_data.recv_bytes()
        except EOFError:
            self._conn_send_message_to_print("DCA1000_Streamer._get_next_frame_packet: DCA1000Handler closed, unable to read data")
            self._conn_send_parent_error_message()
            self._stop_streaming()
            self.streaming_enabled = False
            return
        
        #get sequence number
        packet_seq_num = struct.unpack('<I',msg[0:4])[0]

        #get the byte count
        byte_data = bytearray(msg[4:10])
        byte_data.extend([0x00,0x00])
        packet_byte_count = struct.unpack('<Q',byte_data)[0]

        #check for dropped packets
        self._check_for_dropped_packets(
            packet_seq_num=packet_seq_num,
            packet_byte_count=packet_byte_count)
        
        #increment the number of udp packets received
        self.udp_packet_num = packet_seq_num

        #increment the udp byte count by the number of samples already received
        self.udp_byte_count += len(msg[10:])

        #add the newly recorded samples to the byte buffer
        self.byte_buffer.extend(msg[10:])

        #check for new frames
        self._check_for_new_frame()

        return


    
    def _check_for_dropped_packets(self,packet_seq_num, packet_byte_count):
        """Check for dropped packets and missing samples

        Args:
            packet_seq_num (int): the packet sequence number from the most recently received UDP packet
            packet_byte_count (int): the packet byte count listed in the most recently received UDP packet
        """
        # check for dropped packets
        if packet_seq_num != (self.udp_packet_num + 1):

            #log the dropped packets
            self.dropped_udp_packets += (packet_seq_num - self.udp_packet_num - 1)
        
        #check for dropped samples
        if packet_byte_count > self.udp_byte_count:

            #zero padd the byte_buffer to correct the error
            zero_padding = bytearray(packet_byte_count - self.udp_byte_count)

            self.byte_buffer.extend(zero_padding)

            #update the upp_byte_count
            self.udp_byte_count += len(zero_padding)
    
    def _check_for_new_frame(self):

        #check to see if there are now enough samples for a new frame detection

        if len(self.byte_buffer) >= self.num_bytes_per_frame:

            #save the bytes associated with the new frame
            self.current_packet = self.byte_buffer[:self.num_bytes_per_frame]

            #remove the current packet's bytes from the byte buffer
            if len(self.byte_buffer) == self.num_bytes_per_frame:
                self.byte_buffer = bytearray()
            else:
                self.byte_buffer = self.byte_buffer[self.num_bytes_per_frame:]
            
            #send to the processor
            try:
                self._conn_processor_data.send_bytes(self.current_packet)
            except BrokenPipeError:
                self._conn_send_message_to_print("DCA1000Streamer._check_for_new_frame: attempted to send new packet to Processor, but processor was closed")
                self._conn_send_parent_error_message()
                self._stop_streaming()
                self.streaming_enabled = False
            
            self.num_detected_frames += 1

            #print if verbose is enabled
            if self.verbose:

                #clear the terminal screen
                self._conn_send_clear_terminal()

                #print out the current packet/frame detection results
                self._conn_send_message_to_print("detected frames: {}".format(self.num_detected_frames))
                self._conn_send_message_to_print("\t Total UDP Packets: {}".format(self.udp_packet_num))
                self._conn_send_message_to_print("\t Total UDP Bytes: {}".format(self.udp_byte_count))
                self._conn_send_message_to_print("\t Dropped Packets: {}".format(self.dropped_udp_packets))
            
            return
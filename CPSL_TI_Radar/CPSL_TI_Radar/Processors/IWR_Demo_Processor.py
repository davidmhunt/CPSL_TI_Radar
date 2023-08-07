from multiprocessing.connection import Connection
from multiprocessing import connection,AuthenticationError

from collections import OrderedDict
import numpy as np

from CPSL_TI_Radar.Processors._Processor import _Processor
from CPSL_TI_Radar._Message import _Message,_MessageTypes
from CPSL_TI_Radar.Processors.TLV_Processors._PointCloud import _PointCloudTLVProcessor
from CPSL_TI_Radar.Processors.TLV_Processors._TLVTags import TLVTags


class IWRDemoProcessor(_Processor):
    def __init__(self,
                 conn:Connection,
                 data_connection:Connection,
                 settings_file_path='config_Radar.json'):
        
        super().__init__(conn=conn,
                         settings_file_path=settings_file_path,
                         data_connection=data_connection)
        
        #buffers for processing packets
        self.magic_word = bytearray([0x02,0x01,0x04,0x03,0x06,0x05,0x08,0x07])
        self.header = {}

        #import tlv processor classes
        self.enable_plotting = False
        self.save_plots_as_gifs = False
        self.tlv_processor_detected_objects = None

        self._init_TLV_processes()


        self._conn_send_init_status(self.init_success)
        self.run()

        return
    
    def close(self):
        """End Processor Operations (no custom behavior requred)
        """
        #save gifts to files if they were enabled
        self.tlv_processor_detected_objects.save_gif_to_file()
        return
    
#Loading new radar configurations
    def _load_new_config(self, config_info: dict):
        
        super()._load_new_config(config_info)
    
        #TODO: Update this to support other TLV types
        self.tlv_processor_detected_objects.load_config(
            radar_performance= self.radar_performance,
            radar_config=self.radar_config)
        
        return

#configure TLV processors
    def _init_TLV_processes(self):

        #import tlv processor classes
        self.enable_plotting = self._settings["Processor"]["enable_plotting"]
        self.save_plots_as_gifs = self._settings["Processor"]["save_plots_as_gif"]
        
        self.tlv_processor_detected_objects = _PointCloudTLVProcessor(
            plotting_enabled=self.enable_plotting,
            save_as_gif=self.save_plots_as_gifs)
    
    def _init_listeners(self):

        #get the TLV client initialization information
        TLV_listener_info = self._settings["Processor"]["IWR_Demo_Listeners"]
        
        #generate the authentication string
        authkey_str = TLV_listener_info["authkey"]
        authkey = authkey_str.encode()

        #get the TLV client addresses
        detected_points_address = ('localhost', int(TLV_listener_info["_PointCloudTLVProcessor"]))

        #wait for the TLV clients to connect to their listeners
        try:
            self.tlv_processor_detected_objects.init_conn_client(detected_points_address,authkey)
        except AuthenticationError:
            self._conn_send_message_to_print("IWR_Demo_Processor_init_TLV_listeners: experienced Authentication error when attempting to connect to Client")
            self._conn_send_error_radar_message()


#processing packets
    def _process_new_packet(self):
        
        #load the latest packet from the streamer into the current_packet buffer
        super()._process_new_packet()

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
            self._conn_send_message_to_print("IWR_Demo_Processor_process_TLV: attempted to send data to Listener, but Client process was already closed")
            self._conn_send_error_radar_message()


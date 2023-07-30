from multiprocessing.connection import Connection
from multiprocessing import connection,AuthenticationError

from collections import OrderedDict
import numpy as np

from CPSL_TI_Radar.Processors._Processor import _Processor
from CPSL_TI_Radar._Message import _Message,_MessageTypes
from CPSL_TI_Radar.Processors.TLV_Processors._PointCloud import _PointCloudTLVProcessor
from CPSL_TI_Radar.Processors.TLV_Processors._TLVTags import TLVTags

class DCA1000Processor(_Processor):
    def __init__(self,
                 conn:Connection,
                 data_connection:Connection,
                 settings_file_path='config_Radar.json'):
        
        super().__init__(conn=conn,
                         settings_file_path=settings_file_path,
                         data_connection=data_connection)
        
        self.current_packet = bytearray()

        #TODO: Add code to finish initialization

        self._conn_send_init_status(self.init_success)
        self.run()

        return
    
    def close(self):
        pass

    def _load_new_config(self, config_info: dict):

        #call the parent class method to save the new radar config and performance
        super()._load_new_config(config_info)

        #TODO: add any extra code to load the new configuration
        return

    def _init_listeners(self):
        #TODO: Implement this function
        pass

#processing packets
    def _process_new_packet(self):
        
        #load the packet into the current_packet byte array
        super()._process_new_packet()
    
        #TODO: Add code to process header and packet data
        return
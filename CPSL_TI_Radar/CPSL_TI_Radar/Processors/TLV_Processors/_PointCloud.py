import numpy as np
from collections import OrderedDict
from multiprocessing.connection import Listener


class _PointCloudTLVProcessor:
    def __init__(self, plotting_enabled=True, save_as_gif=False):
        self.detected_objects: np.array(type=np.float32)

        # storing radar performance variables
        self.radar_performance: dict = None
        self.radar_config = OrderedDict()

        # TLV client connection to send data to an external process
        self._conn_listener_enabled = False
        self._listener = None
        self._conn_listener = None

    def load_config(self, radar_performance: dict, radar_config: OrderedDict):
        # load the new radar performance values
        self.radar_performance = radar_performance
        self.radar_config = radar_config

    # Sending data to an external process
    def init_conn_client(self, address, authkey):
        """initialize the client connection to send data to an external process

        Args:
            address (tuple): address in the form ('localhost',address)
            authkey (binary string): authentication key in the form b'authkey'
        """

        # setup a new connection with a listener at the address
        # blocks until the connection is established
        self._listener = Listener(address, authkey=authkey)
        self._conn_listener = self._listener.accept()
        self._conn_listener_enabled = True

    # processing data
    def process_new_data_6843(self,data:bytearray):
        
        #access the points as a float
        points = np.frombuffer(data[8:],dtype=np.float32)

        #reshape so that each row corresponds to a specific object
        points = points.reshape([-1,4])

        self.detected_objects = points

        if self._conn_listener_enabled:
            self._conn_listener.send(self.detected_objects)

        return

    def process_new_data_1443(self, data: bytearray):
        descriptor = np.frombuffer(data[8:12], dtype=np.uint16)
        num_objects = descriptor[0]
        XYZQ_format = descriptor[1]
        XYZQ_conversion = np.power(2, XYZQ_format)

        # start forming the detected objects array
        objects_struct = np.frombuffer(data[12:], dtype=np.int16)
        # reshape so that each row corresponds to a specific object
        objects_struct = objects_struct.reshape([-1, 6])

        range_idxs = objects_struct[:, 0].astype(np.uint16)
        ranges = np.float32(
            range_idxs * self.radar_performance["range"]["range_idx_to_m"]
        )

        vel_idxs = objects_struct[:, 1]
        vels = np.float32(
            vel_idxs * self.radar_performance["velocity"]["vel_idx_to_m_per_s"]
        )

        peak_vals = (objects_struct[:, 2] / XYZQ_conversion).astype(np.float32)

        XYZ_coordinates = (objects_struct[:, 3:] / XYZQ_conversion).astype(np.float32)

        self.detected_objects = np.concatenate(
            (
                XYZ_coordinates,
                vels[:, np.newaxis],
                ranges[:, np.newaxis],
                peak_vals[:, np.newaxis],
            ),
            axis=1,
        )

        if self._conn_listener_enabled:
            self._conn_listener.send(self.detected_objects)

        return

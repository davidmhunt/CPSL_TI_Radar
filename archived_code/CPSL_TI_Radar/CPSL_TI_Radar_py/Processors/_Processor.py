from multiprocessing.connection import Connection
from multiprocessing import connection, AuthenticationError

from collections import OrderedDict
import numpy as np
import sys

from CPSL_TI_Radar._Background_Process import _BackgroundProcess
from CPSL_TI_Radar._Message import _Message, _MessageTypes
from CPSL_TI_Radar.Processors.TLV_Processors._PointCloud import _PointCloudTLVProcessor


class TLVTags:
    DETECTED_POINTS = 1
    RANGE_PROFILE = 2
    NOISE_PROFILE = 3
    AZIMUTH_STATIC_HEAT_MAP = 4
    RANGE_DOPPLER_HEAT_MAP = 5
    STATS = 6


class _Processor(_BackgroundProcess):
    def __init__(
        self,
        conn_parent: Connection,
        conn_processor_data: Connection,
        settings_file_path="config_Radar.json",
    ):
        """Initialization process for parent Processor class

        Args:
            conn_parent (connection): connection to the parent process (RADAR)
            conn_processor_data (Connection): connection to pass data between Processors and Streamers.
            settings_file_path (str, optional): path to the RADAR config file. Defaults to 'config_RADAR.json'.
        """

        super().__init__(
            process_name="Processor",
            conn_parent=conn_parent,
            conn_processor_data=conn_processor_data,
            conn_handler_data=None,
            settings_file_path=settings_file_path,
        )

        #determine the IWR type
        self.sdk_version = None
        self.init_SDK_version()
            #options are "IWR1443" and "IWR6843"
        
        # byte array for the current packet of data
        self.current_packet = bytearray()

        # radar performance specs for the given config
        self.config_loaded = False
        self.radar_performance = {}
        self.radar_config = OrderedDict()

        # initialize the streaming status
        self.streaming_enabled = False

        # set the verbose status
        self.verbose = self._settings["Processor"]["verbose"]

        return

    def init_SDK_version(self):

        #set the IWR type
        try:
            self.sdk_version = self._settings["Processor"]["SDK_version"]

            if self.sdk_version not in ["3.5","2.1"]:
                self._conn_send_message_to_print(
                "Processor.__init__: SDK Version ({}) is invalid".format(self.sdk_version))
                self._conn_send_init_status(init_success=False)
                self.init_success = False
                sys.exit()
        except KeyError:
            self._conn_send_message_to_print(
                "Processor.__init__: could not find SDK_version in json config")
            self._conn_send_init_status(init_success=False)
            self.init_success = False
            sys.exit()

    def run(self):
        try:
            while self.exit_called == False:
                # process new messages from either the Radar or the
                if self.streaming_enabled:
                    # wait until either the Radar or the Processor sends data
                    ready_conns = connection.wait(
                        [self._conn_parent, self._conn_processor_data], timeout=None
                    )
                    for conn in ready_conns:
                        if conn == self._conn_parent:
                            self._conn_process_Radar_command()
                        else:  # must be new data available
                            self._process_new_packet()
                else:
                    self._conn_process_Radar_command()

            self.close()
        except KeyboardInterrupt:
            self.close()
            sys.exit()

        return

    def close(self):
        """End Processor Operations (no custom behavior requred)"""

        # TODO: implement in child class
        pass

    # configure TLV processors
    def _init_TLV_processes(self):
        # import tlv processor classes
        self.enable_plotting = self._settings["Processor"]["enable_plotting"]
        self.save_plots_as_gifs = self._settings["Processor"]["save_plots_as_gif"]

        self.tlv_processor_detected_objects = _PointCloudTLVProcessor(
            plotting_enabled=self.enable_plotting, save_as_gif=self.save_plots_as_gifs
        )

    def _init_listeners(self):
        # TODO: Implement in child process
        pass

    # processing packets
    def _process_new_packet(self):
        # receive the latest packet from the processor
        # TODO: currently a risk of the processor dropping packets here
        while self._conn_processor_data.poll():
            try:
                self.current_packet = self._conn_processor_data.recv_bytes()
            except EOFError:
                self._conn_send_message_to_print(
                    "Processor._process_new_packet: attempted to receive new packet from Streamer, but streamer was closed"
                )
                self._conn_send_parent_error_message()
                self.streaming_enabled = False
                return

        # TODO: Define remaining custom behavior to actually process the packet

        return

    # Loading new radar configurations
    def _load_new_config(self, config_info: dict):
        """Load a new set of radar performance and radar configuration dictionaries into the processor class

        Args:
            config_info (dict): Dictionary with entries for "radar_config" and "radar_performance"
        """
        # load a new set of radar performance specs and radar configuration dictionaries into the processor class
        self.radar_config = config_info["radar_config"]
        self.radar_performance = config_info["radar_performance"]

        # set config loaded flag
        self.config_loaded = True

    # Streaming/processing of radar samples
    def _start_streaming(self):
        """sets the streaming_enabled flag to true. Checks to make sure that a configuration is loaded first"""
        if self.config_loaded == False:
            self._conn_send_message_to_print(
                "Processor._start_streaming: Attempted to start streaming without loading a configuration first"
            )
            self._conn_send_parent_error_message()
        else:
            self.streaming_enabled = True

        return

    def _conn_process_Radar_command(self):
        """Wait for and then execute commands from the Radar class. Sends the command type back to the Radar as confirmation that the command has been performed"""

        command: _Message = self._conn_parent.recv()
        match command.type:
            case _MessageTypes.EXIT:
                self.exit_called = True
            case _MessageTypes.LOAD_NEW_CONFIG:
                self._load_new_config(command.value)
            case _MessageTypes.START_STREAMING:
                self._start_streaming()
            case _MessageTypes.STOP_STREAMING:
                self.streaming_enabled = False
            case _MessageTypes.CONFIG_LISTENERS:
                self._init_listeners()
                self._conn_send_command_executed_message(_MessageTypes.CONFIG_LISTENERS)
            case _:
                self._conn_send_message_to_print(
                    "Processor._process_Radar_command: command not recognized"
                )
                self._conn_send_parent_error_message()

        self._conn_send_command_executed_message(command.type)

        return

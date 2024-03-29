import socket
import struct
from CPSL_TI_Radar._Message import _Message
from CPSL_TI_Radar._Message import _MessageTypes
from CPSL_TI_Radar._Background_Process import _BackgroundProcess
import sys

from multiprocessing.connection import Connection


class DCA1000CommandCodes:
    RESET_FPGA = 0x01
    RESET_AR_DEV = 0x02
    CONFIG_FPGA_GEN = 0x03
    CONFIG_EEPROM = 0x04
    RECORD_START = 0x05
    RECORD_STOP = 0x06
    PLAYBACK_START = 0x07
    PLAYBACK_STOP = 0x08
    SYSTEM_CONNECT = 0x09
    SYSTEM_ERROR = 0x0A
    CONFIG_PACKET_DATA = 0x0B
    CONFIG_DATA_MODE_AR_DEV = 0x0C
    INIT_FPGA_PLAYBACK = 0x0D
    READ_FPGA_VERSION = 0x0E


class DCA1000Handler(_BackgroundProcess):
    def __init__(
        self,
        conn_parent: Connection,
        conn_handler_data: Connection,
        settings_file_path="config_RADAR.json",
    ):
        """Initialize the DCA1000 handler for given ip address, command port, and data port

        Args:
            ip_address (str, optional): IP address of DCA1000 FPGA. Defaults to '1.9.168.33.180'.
            cmd_port (int, optional): Port for DCA1000 command interfaces. Defaults to 4096.
            data_port (int, optional): Port for DCA1000 raw data streaming. Defaults to 4098.
        Returns:
            bool: True if DCA1000 initialized correctly, False if not
        """

        # initialize background process parent class
        super().__init__(
            "DCA1000Handler",
            conn_parent=conn_parent,
            settings_file_path=settings_file_path,
            conn_processor_data=None,
            conn_handler_data=conn_handler_data,
        )

        # connectivity
        self.system_IP = None
        self.FPGA_IP = None

        # FPGA version
        self.FPGA_version: str = None

        # commands
        self.cmd_port = None
        self.cmd_socket = None
        self.cmd_socket_bound = False
        self.cmd_header = 0xA55A
        self.cmd_footer = 0xEEAA

        # data streaming
        self.data_port = None
        self.data_socket = None
        self.data_socket_bound = False
        self.streaming_enabled = False

        # initialize connection information
        self._init_DCA1000_connection_information()

        # connect to data capture board
        self._init_ethernet_sockets()

        # configure the FPGA if init_success is still true
        if self.init_success:
            self._init_DCA1000_FPGA()

        # if the FPGA was initialized successfully, send the version of the FPGA to print
        if self.init_success:
            out_str = (
                "DCA1000Handler: Initialized successfully with FPGA Version {}".format(
                    self.FPGA_version
                )
            )
            self._conn_send_message_to_print(out_str)

        self._conn_send_init_status(self.init_success)

        self.run()
        return

    def _init_DCA1000_connection_information(self):
        # get the ip address
        self.system_IP = self._settings["Streamer"]["DCA1000_streaming"]["system_IP"]
        self.FPGA_IP = self._settings["Streamer"]["DCA1000_streaming"]["FPGA_IP"]
        self.data_port = self._settings["Streamer"]["DCA1000_streaming"]["data_port"]
        self.cmd_port = self._settings["Streamer"]["DCA1000_streaming"]["cmd_port"]

    def _init_ethernet_sockets(self):
        """Bind to the cmd and data ethernet ports. Handle errors accordingly"""

        # bind to command socket
        try:
            self.cmd_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Default, set the socket to send/receive from ("192.168.33.30",4098)
            self.cmd_socket.bind((self.system_IP, self.cmd_port))
            self.cmd_socket_bound = True
            self.cmd_socket.settimeout(1)
        except socket.error:
            self._conn_send_message_to_print(
                "DCA1000._init_ethernet_sockets: Failed to connect to cmd socket"
            )
            self.init_success = False

        # bind to data socket
        try:
            self.data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Default, set the socket to send/receive from ("192.168.33.30",4098)
            self.data_socket.bind((self.system_IP, self.data_port))
            self.data_socket_bound = True
            self.data_socket.settimeout(1)
        except socket.error:
            self._conn_send_message_to_print(
                "DCA1000._init_ethernet_sockets: Failed to connect to data socket"
            )
            self.init_success = False

    def close(self):
        """Close all sockets if they are currently open"""
        if self.streaming_enabled:
            self._stop_streaming()

        if self.cmd_socket_bound:
            self.cmd_socket.close()
        if self.data_socket_bound:
            self.data_socket.close()

    def run(self):
        try:
            while self.exit_called == False:
                if self.streaming_enabled:
                    # get the next udp packet
                    self.get_next_udp_packet()
                    if self._conn_parent.poll():
                        while self._conn_parent.poll():
                            # while commands are available from the streamer process them
                            self._conn_process_parent_command()

                else:
                    self._conn_process_parent_command()

            self.close()

        except KeyboardInterrupt:
            self.close()
            sys.exit()

    # initializing the DCA1000 FPGA
    def _init_DCA1000_FPGA(self):
        """Send commands to initialize the DCA1000 and obtain the FPGA version"""

        # DCA1000 status returns 0 if successful, 1 if not
        num_fails = 0

        # send System_connect
        self._send_command(DCA1000CommandCodes.SYSTEM_CONNECT)
        num_fails += self._recv_command_response(DCA1000CommandCodes.SYSTEM_CONNECT)

        # send FPGA RESET Command
        self._send_command(DCA1000CommandCodes.RESET_FPGA)
        num_fails += self._recv_command_response(DCA1000CommandCodes.RESET_FPGA)

        # CONFIG_PACKET_DATA
        self._send_CONFIG_PACKET_DATA()
        num_fails += self._recv_command_response(DCA1000CommandCodes.CONFIG_PACKET_DATA)

        # send CONFIG_FPGA_GEN
        self._send_CONFIG_FPGA_GEN()
        num_fails += self._recv_command_response(DCA1000CommandCodes.CONFIG_FPGA_GEN)

        # send READ_FPGA_VERSION
        self._send_command(DCA1000CommandCodes.READ_FPGA_VERSION)
        FPGA_version = self._recv_command_response(
            DCA1000CommandCodes.READ_FPGA_VERSION
        )
        self._decode_FPGA_version(FPGA_version)

        # check init satus
        if num_fails > 0:
            self._conn_send_message_to_print(
                "DCA1000._init_DCA1000_FPGA: {} commands failed".format(num_fails)
            )
            self.init_success = False

        return

    # sending and receiving commands to DCA1000 FPGA
    def _send_command(self, command_code: int, data: bytearray = None):
        """Send command to the DCA1000

        Args:
            command_code (int): Command Code to send
            data (bytearray, optional): Data associated with the command. Defaults to None.
        """

        # create the byte array
        msg = bytearray()

        # add the header (formatted as little-endian)
        msg.extend(struct.pack("<H", self.cmd_header))

        # add the message code
        msg.extend(struct.pack("<H", command_code))

        # add the data length
        if data:
            num_bytes = len(data)
            # convert the num_bytes to a uint16 and add to the byte array
            msg.extend(bytearray(struct.pack("<H", num_bytes)))

            # add the data
            msg.extend(data)
        else:
            msg.extend(struct.pack("<H", 0))

        # add the footer
        msg.extend(struct.pack("<H", self.cmd_footer))

        # send the command
        if self.cmd_socket_bound:
            # send to the FPGA address, Default ("192.168.33.180,4096")
            self.cmd_socket.sendto(msg, (self.FPGA_IP, self.cmd_port))
        else:
            print("DCA1000._send_command: cmd_socket is not connected")

    def _recv_command_response(self, command_code: int):
        """Receive the response from a given command code

        Args:
            command_code (int): the command code for the command that was sent

        Returns:
            status: the status of the received command
        """

        if self.cmd_socket_bound:
            # receive the messgae
            msg, server = self.cmd_socket.recvfrom(2048)

            header = "".join("{:02x}".format(x) for x in struct.unpack("<H", msg[0:2]))
            recv_cmd_code = struct.unpack("<H", msg[2:4])[0]
            status = struct.unpack("<H", msg[4:6])[0]
            footer = "".join("{:02x}".format(x) for x in struct.unpack("<H", msg[6:8]))

            if recv_cmd_code == command_code:
                return status
            else:
                # TODO: add exception handling here
                return status
        else:
            # TODO: add exception handling here
            print("DCA1000._receive_command_response: cmd_socket is not connected")
            return 0x00

    # custom commands/responses to DCA1000 FPGA
    def _send_CONFIG_PACKET_DATA(self):
        """Send command to configure the packet data on the FPGA"""

        # determine the data to send to configure the FPGA
        data = bytearray()

        # define packet size to 1470 bytes
        data.extend(struct.pack("<H", 1470))

        # define packet delay to 25us
        data.extend(struct.pack("<H", 25))

        # add "future use" part of command
        data.extend(bytearray([0x00, 0x00]))

        self._send_command(DCA1000CommandCodes.CONFIG_PACKET_DATA, data)

    def _send_CONFIG_FPGA_GEN(self):
        """Configure the FPGA data formatting"""
        # initialize array to store bytes used to configure FPGA
        data = bytearray()

        # data logging mode - set to Raw Mode
        data.append(0x01)

        # LVDS mode - 4 lane mode
        data.append(0x01)

        # data transfer mode - lvds mode
        data.append(0x01)

        # data capture mode - ethernet stream
        data.append(0x02)

        # data format - 16 bit
        data.append(0x03)

        # timer - default to 30 seconds
        data.append(0x1E)

        self._send_command(DCA1000CommandCodes.CONFIG_FPGA_GEN, data)

    def _decode_FPGA_version(self, recieved_message: int):
        """Decode the FPGA version and save it in the FPGA_version variable

        Args:
            recieved_message (int): the raw status message received from the DCA1000 decoded as uint16
        """

        # convert to uint16 in little-endian format
        byte_data = struct.pack(">H", recieved_message)

        major_version = int(byte_data[1]) & 0b01111111
        minor_version = int.from_bytes(byte_data, byteorder="big") >> 7

        self.FPGA_version = "{}.{}".format(major_version, minor_version)

    # obtaining packets from the DCA1000 FPGA
    def get_next_udp_packet(self):
        try:
            msg, server = self.data_socket.recvfrom(1472)
        except socket.error as e:
            self._conn_send_message_to_print(
                "DCA1000Handler.get_next_udp_packet: experienced the following socket error when attempting to get next packet:{}".format(
                    e
                )
            )
            self._conn_send_parent_error_message()
            self._stop_streaming()
            self.streaming_enabled = False
            return

        # send the message to the streamer class
        try:
            self._conn_handler_data.send_bytes(msg)
        except BrokenPipeError:
            self._conn_send_message_to_print(
                "DCA1000Handler.get_next_udp_packet: attempted to send new udp packet to Streamer, but streamer was closed"
            )
            self._conn_send_parent_error_message()
            self._stop_streaming()
            self.streaming_enabled = False

    # Handle starting and stopping streaming
    def _start_streaming(self):
        """Start streaming on DCA1000"""

        # success is true if streaming is enabled
        success = True
        if self.data_socket_bound == True:
            if self.streaming_enabled == False:
                # send record start command
                self._send_command(DCA1000CommandCodes.RECORD_START)

                # receive confirmation that recording has started
                status = self._recv_command_response(DCA1000CommandCodes.RECORD_START)

                if status == 0:
                    success = True  # streaming started successfully
                else:
                    success = False  # error occured when attempting to start streaming
            else:
                success = True  # streaming was already going
        else:
            success = False  # socket was not yet bounded

        if success:
            self.streaming_enabled = True
        else:
            self.streaming_enabled = False
            self._conn_send_message_to_print(
                "DCA1000_Handler_start_streaming: experienced error when attempting to start streaming"
            )
            self._conn_send_parent_error_message()

    def _stop_streaming(self):
        """Stop streaming on the DCA1000

        Returns:
            bool: True if streaming stopped successfully, False if not
        """

        # success is true if streaming stopped successfully
        success = True

        if self.data_socket_bound == True:
            if self.streaming_enabled == True:
                # send record start command
                self._send_command(DCA1000CommandCodes.RECORD_STOP)

                # receive confirmation that recording has started
                status = self._recv_command_response(DCA1000CommandCodes.RECORD_STOP)

                if status == 0:
                    self.streaming_enabled = False
                    success = True  # streaming started successfully
                else:
                    success = False  # error occured when attempting to start streaming
            else:
                success = True  # streaming was already going
        else:
            success = False  # socket was not yet bounded

        if success:
            self.streaming_enabled = False
        else:
            self.streaming_enabled = False  # disable streaming due to error
            self._conn_send_message_to_print(
                "DCA1000_Handler_start_streaming: experienced error when attempting to start streaming"
            )
            self._conn_send_parent_error_message()

    # Handle communication with parent (streamer class)
    def _conn_process_parent_command(self):
        command: _Message = self._conn_parent.recv()
        match command.type:
            case _MessageTypes.EXIT:
                self.exit_called = True
            case _MessageTypes.START_STREAMING:
                self._start_streaming()
            case _MessageTypes.STOP_STREAMING:
                self._stop_streaming()
            case _:
                self._conn_send_message_to_print(
                    "DCA1000Handler._process_Streamer_command: command not recognized"
                )
                self._conn_send_parent_error_message()

        self._conn_send_command_executed_message(command.type)

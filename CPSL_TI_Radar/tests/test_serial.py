import serial.tools.list_ports
import serial
import json
import os
import sys
import socket
import struct

#define the configuration file path
config_file_path = os.path.abspath("CPSL_TI_Radar_settings.json")
#testing functions

#test to check that the serial ports work
def parse_json(json_file_path):
    """Read a json file at the given path and return a json object

    Args:
        json_file_path (str): path to the JSON file

    Returns:
        _type_: json
    """

    # open the JSON file
    f = open(json_file_path)
    content = ""
    for line in f:
        content += line
    return json.loads(content)

def test_config_file_present():

    current_dir = os.getcwd()
    file_exists = os.path.isfile(config_file_path)
    if file_exists:
        settings = parse_json(config_file_path)

    assert file_exists, "Couldn't find {} in {}".format(config_file_path,current_dir)

def test_cli_serial():
    
    #verify that the config file exists
    file_exists = os.path.isfile(config_file_path)
    assert file_exists, "Config file not found, unable to perform test"
    settings = parse_json(config_file_path)

    #get the two serial ports from the configuration
    cli_serial_port_address = settings["CLI_Controller"]["CLI_port"]
    baud_rate = 115200
    timeout=30e-3

    #get list of available ports
    available_ports = [
            comport.device for comport in serial.tools.list_ports.comports()
        ]
    connection_successful = False

    try:
        cli_serial_port = serial.Serial(cli_serial_port_address, baud_rate, timeout=timeout)
        connection_successful = True
        
    except serial.SerialException:
        connection_successful = False
    
    assert connection_successful, "CLI Controller port {} not in available ports: {}".format(cli_serial_port_address,available_ports)

def test_streamer_connection():
    #verify that the config file exists
    file_exists = os.path.isfile(config_file_path)
    assert file_exists, "Config file not found, unable to perform test"
    settings = parse_json(config_file_path)

    if settings["Streamer"]["serial_streaming"]["enabled"]:
        check_streamer_serial()
    
    elif settings["Streamer"]["DCA1000_streaming"]["enabled"]:
        check_streamer_DCA1000()

def check_streamer_serial():

    settings = parse_json(config_file_path)
    data_port = settings["Streamer"]["serial_streaming"]["data_port"]

    cli_serial_port_address = settings["CLI_Controller"]["CLI_port"]
    baud_rate = 115200
    timeout=30e-3

    #get list of available ports
    available_ports = [
            comport.device for comport in serial.tools.list_ports.comports()
        ]
    connection_successful = False

    try:
        cli_serial_port = serial.Serial(cli_serial_port_address, baud_rate, timeout=timeout)
        connection_successful = True
        
    except serial.SerialException:
        connection_successful = False
    
    assert connection_successful, "Serial Streaming port {} not in available ports: {}".format(cli_serial_port_address,available_ports)

def check_streamer_DCA1000():

    settings = parse_json(config_file_path)

    #get DCA1000 connection information
    system_IP = settings["Streamer"]["DCA1000_streaming"]["system_IP"]
    FPGA_IP = settings["Streamer"]["DCA1000_streaming"]["FPGA_IP"]
    data_port = settings["Streamer"]["DCA1000_streaming"]["data_port"]
    cmd_port = settings["Streamer"]["DCA1000_streaming"]["cmd_port"]

    #test connections to DCA1000 via ethernet
    # bind to command socket
    init_success = False
    try:
        cmd_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Default, set the socket to send/receive from ("192.168.33.30",4098)
        cmd_socket.bind((system_IP, cmd_port))
        cmd_socket_bound = True
        cmd_socket.settimeout(1)
        init_success = True
    except socket.error:
        init_success = False
    assert init_success, "Failed to connect to cmd socket"

    # bind to data socket
    init_success = False
    try:
        data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Default, set the socket to send/receive from ("192.168.33.30",4098)
        data_socket.bind((system_IP, data_port))
        data_socket_bound = True
        data_socket.settimeout(1)
        init_success = True
    except socket.error:
        init_success = False
    assert init_success, "Failed to connect to cmd socket"

    #send sample bytes
    SYSTEM_CONNECT = 0x09
    READ_FPGA_VERSION = 0x0E

    #send FPGA system connect
    # DCA1000 status returns 0 if successful, 1 if not
    num_fails = 0

    # send System_connect
    send_command(cmd_socket,FPGA_IP,cmd_port,SYSTEM_CONNECT)
    num_fails += recv_command_response(cmd_socket,SYSTEM_CONNECT)

    # # send FPGA RESET Command
    # send_command(RESET_FPGA)
    # num_fails += recv_command_response(RESET_FPGA)

    # # CONFIG_PACKET_DATA
    # send_CONFIG_PACKET_DATA()
    # num_fails += recv_command_response(CONFIG_PACKET_DATA)

    # # send CONFIG_FPGA_GEN
    # send_CONFIG_FPGA_GEN()
    # num_fails += recv_command_response(CONFIG_FPGA_GEN)

    # send READ_FPGA_VERSION
    send_command(cmd_socket,FPGA_IP,cmd_port,READ_FPGA_VERSION)
    FPGA_version = recv_command_response(cmd_socket,READ_FPGA_VERSION)
    decode_FPGA_version(FPGA_version)

    # check init satus
    assert num_fails == 0, "Failed to initialize DCA1000 FPGA"

    return

def recv_command_response(cmd_socket:socket.socket, command_code: int):
    """Receive the response from a given command code

    Args:
        command_code (int): the command code for the command that was sent

    Returns:
        status: the status of the received command
    """

    msg, server = cmd_socket.recvfrom(2048)

    header = "".join("{:02x}".format(x) for x in struct.unpack("<H", msg[0:2]))
    recv_cmd_code = struct.unpack("<H", msg[2:4])[0]
    status = struct.unpack("<H", msg[4:6])[0]
    footer = "".join("{:02x}".format(x) for x in struct.unpack("<H", msg[6:8]))

    assert recv_cmd_code == command_code, "expected to receive cmd code: {}, but got {}".format(recv_cmd_code,command_code)
    
    return status

def send_command(cmd_socket:socket.socket, FPGA_IP, cmd_port, command_code):
    """Send command to the DCA1000

    Args:
        command_code (int): Command Code to send
        data (bytearray, optional): Data associated with the command. Defaults to None.
    """
    cmd_header = 0xA55A
    cmd_footer = 0xEEAA

    # create the byte array
    msg = bytearray()

    # add the header (formatted as little-endian)
    msg.extend(struct.pack("<H", cmd_header))

    # add the message code
    msg.extend(struct.pack("<H", command_code))

    # add the data length
    msg.extend(struct.pack("<H", 0))

    # add the footer
    msg.extend(struct.pack("<H", cmd_footer))

    # send the command
    cmd_socket.sendto(msg, (FPGA_IP, cmd_port))

def decode_FPGA_version(received_messsage: int):
        """Decode the FPGA version and save it in the FPGA_version variable

        Args:
            recieved_message (int): the raw status message received from the DCA1000 decoded as uint16
        """

        # convert to uint16 in little-endian format
        byte_data = struct.pack(">H", received_messsage)

        major_version = int(byte_data[1]) & 0b01111111
        minor_version = int.from_bytes(byte_data, byteorder="big") >> 7

        FPGA_version = "{}.{}".format(major_version, minor_version)

        return FPGA_version

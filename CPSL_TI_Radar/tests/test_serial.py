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
        cmd_socket.settimeout(1e-3)
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
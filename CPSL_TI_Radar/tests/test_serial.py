import serial.tools.list_ports
import serial
import json
import os
import socket
import struct

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

def test_cli_serial(json_config_path):
    
    #verify that the config file exists
    file_exists = os.path.isfile(json_config_path)
    assert file_exists, "Config file not found, unable to perform test"
    settings = parse_json(json_config_path)

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

def test_streamer_serial(json_config_path):
    #verify that the config file exists
    file_exists = os.path.isfile(json_config_path)
    assert file_exists, "Config file not found, unable to perform test"
    settings = parse_json(json_config_path)

    if settings["Streamer"]["serial_streaming"]["enabled"]:

        data_port = settings["Streamer"]["serial_streaming"]["data_port"]

        baud_rate = 921600
        timeout=0.5

        #get list of available ports
        available_ports = [
                comport.device for comport in serial.tools.list_ports.comports()
            ]
        connection_successful = False

        try:
            cli_serial_port = serial.Serial(data_port, baud_rate, timeout=timeout)
            connection_successful = True
            
        except serial.SerialException:
            connection_successful = False
        
        assert connection_successful, "Serial Streaming port {} not in available ports: {}".format(cli_serial_port_address,available_ports)

    else:
        assert True #automatic pass as no serial streaming
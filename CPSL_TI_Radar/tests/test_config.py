import serial.tools.list_ports
import serial
import json
import os

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

def test_config_valid(json_config_path):

    file_exists = os.path.isfile(json_config_path)
    if file_exists:
        settings = parse_json(json_config_path)

    assert file_exists, "Couldn't find {} in {}".format(json_config_path,os.getcwd())

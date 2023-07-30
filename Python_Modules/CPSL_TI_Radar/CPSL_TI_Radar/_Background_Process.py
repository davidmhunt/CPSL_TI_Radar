from multiprocessing.connection import Connection
from CPSL_TI_Radar._Message import _Message,_MessageTypes
import json
import os
import sys
import serial
import serial.tools.list_ports

class _BackgroundProcess:
    def __init__(self,
                 process_name,
                 conn:Connection,
                 config_file_path = 'config_RADAR.json',
                 data_connection:Connection = None):
        """Initialization process for all background processes

        Args:
            process_name (str): the name of the process
            conn (connection): connection to the parent process (RADAR)
            config_file_path (str, optional): path to the RADAR config file. Defaults to 'config_RADAR.json'.
        """
        
        #processes exit flag (call from RADAR to exit the process)
        #NOTE: This should only be triggerred by the Radar class or by a keyboard interrupt
        self.exit_called = False
        
        #init success flag
        self.init_success = True
        
        #save process name
        self._process_name = process_name
        
        #establish connection to the parent class (radar)
        self._conn_RADAR = conn

        #establish a connection to send byte data between processes
        self._conn_data = data_connection

        #initialize variable for a serial port
        self.serial_port = None

        #get the Radar class configuration as well
        try:
            self.config_Radar = self._parse_JSON(config_file_path)
        except FileNotFoundError:
            self._conn_send_message_to_print("{}.__init__: could not find {} in {}".format(self._process_name, config_file_path,os.getcwd()))
            self._conn_send_init_status(init_success=False)
            self.init_success = False
            sys.exit()
        
        return
    
## Parse JSON files and store for later use
    def _parse_JSON(self,json_file_path):
        """Read a json file at the given path and return a json object

        Args:
            json_file_path (str): path to the JSON file

        Returns:
            _type_: json
        """
        
        #open the JSON file
        f = open(json_file_path)
        content = ''
        for line in f:
            content += line
        return json.loads(content)

## Initialize a serial port if required

    def _serial_init_serial_port(
            self,
            address:str,baud_rate,
            timeout=1,
            close:bool = False):
        """Initializze the serial port

        Args:
            address (str): serial port address (on windows "Serial1"),
                (on Linux, try either "/dev/ttyACM1, or /dev/ttyUSB1)
            baud_rate (int): baud rate of the serial connection
            timeout (int, optional): Timeout duration in seconds. Defaults to 1.
            close (bool, optional): Closes the serial port on True. Defaults to False.

        Returns:
            bool: True on successful initialization. False when cannot find serial port
        """
        
        #initialize the serial port
        try:
            self.serial_port = serial.Serial(address,baud_rate,timeout=timeout)
            #reset the buffers in case old data is on the serial line
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()
            if close:
                self.serial_port.close()
            return True
        except serial.SerialException:
            #get the available serial ports
            available_ports = [comport.device for comport in serial.tools.list_ports.comports()]
            
            #send the error message
            self._conn_send_message_to_print(
                "{}.__init__:could not find serial port{}. Available ports are: {}".format(
                self._process_name,
                address,
                available_ports))
            self._conn_send_init_status(init_success=False)
            self.init_success = False
            return False

## Handling inter-process communications between different processes
    def _conn_send_init_status(self,init_success:bool = True):
        """Send the initialization status back to the radar class

        Args:
            init_success (bool, optional): True if initialization was successful. Defaults to True.
        """
        
        #determine which message to send
        if init_success == True:
            msg = _Message(_MessageTypes.INIT_SUCCESS)
        else:
            msg = _Message(_MessageTypes.INIT_FAIL)
        
        self._conn_RADAR.send(msg)
    
    def _conn_send_message_to_print(self,message:str):
        """Send a message to the Radar object to print on the terminal

        Args:
            message (str): The message to be printed on the terminal
        """
        self._conn_RADAR.send(_Message(_MessageTypes.PRINT_TO_TERMINAL,message))

    def _conn_send_clear_terminal(self):
        """Send message for Radar object to clear the terminal
        """
        self._conn_RADAR.send(_Message(_MessageTypes.PRINT_CLEAR_TERMINAL))
    
    def _conn_send_error_radar_message(self):
        """Sends a ERROR_RADAR message to let Radar know something has gone wrong
        """

        self._conn_RADAR.send(_Message(_MessageTypes.ERROR_RADAR))
    
    def _conn_send_command_executed_message(self,command:_MessageTypes):
        """Send command executed message notifying RADAR class that the 
        specified command was successfully performed

        Args:
            command (_MessageTypes): The command that was successfully executed
        """

        self._conn_RADAR.send(
            _Message(
                type=_MessageTypes.COMMAND_EXECUTED,
                value=command))
        return
## Essential functions for all _BackgroundProcess classes
    def run(self):
        pass

    def close(self):
        pass
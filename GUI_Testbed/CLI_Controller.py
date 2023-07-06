import sys
import os
import serial
import time
from _Background_Process import _BackgroundProcess
from multiprocessing.connection import Connection
from _Message import _Message,_MessageTypes

class CLIController(_BackgroundProcess):
    """The controller class handles CLI command and control with the radar
    """

    def __init__(
            self,
            conn:Connection,
            config_file_path='config_Radar.json'):
        """Initialize the controller class

        Args:
            config_file_path (str): _description_
        """
        super().__init__("CLI_Controller",
                       conn,
                       config_file_path)       

        #load the class variables
        self.TI_Radar_config_path = ""
        self.TI_Radar_config_loaded = False
        self.verbose = self.config_Radar["CLI_Controller"]["verbose"]

        #initialize the serial port
        self._serial_init_serial_port(
            address=self.config_Radar["CLI_Controller"]["CLI_port"],
            baud_rate= 115200,
            timeout=30e-3
        )
        
        #send configuration file to the device
        self.sensor_running = False

        #send successful init status if successful
        self._conn_send_init_status(init_success=self.init_success)
        self.run()

        return

    def run(self):
        try:
            while self.exit_called == False:
                msg = self._conn_RADAR.recv()
                self._conn_process_Radar_command(msg)

            #once exit is called close out and return
            self.close()
        except KeyboardInterrupt:
            self.close()
            sys.exit()
    
    def close(self):
        #before exiting, close the serial port and turn the sensor off
        if self.serial_port.is_open == True:
            #turn the sensor off
            if self.sensor_running == True:
                self.serial_send_stop_sensing()

            #close the serial port
            self.serial_port.close()
    
    def serial_send_config(self):
        """Send the TI Radar configuration over serial, but do not start radar sensing
        """
        #confirm that a config file path has been loaded
        if self.TI_Radar_config_loaded == False:
            self._conn_send_message_to_print("CLI_Controller.send_config: no config file path loaded")
            self._conn_send_error_radar_message()
            return

        #load in the TI Radar config file
        try:
            config = [line.rstrip('\r\n') for line in open(self.TI_Radar_config_path)]
        except FileNotFoundError:
            self._conn_send_message_to_print("CLI_Controller.send_config:could not find {}".format(self.TI_Radar_config_path))
            self._conn_send_error_radar_message()
            return

        #send every command except for the sensor start command
        successful_send = True
        for command in config:
            if(command != "sensorStart"):
                successful_send = self._serial_send_command(command)
                if not successful_send:
                    return
            #don't send a sensor start command
            elif (command == "sensorStart"):
                if self.verbose:
                    self._conn_send_message_to_print("Config.sendConfigSerial: 'sensorStart' in config file. Skipping sensorStart command")
        

    
    def serial_send_start_sensing(self):
        """Send the sensorStart command to the sensor to begin sensing
        """
        successful_send = self._serial_send_command("sensorStart")
        if not successful_send:
            self.sensor_running = False
        else:
            self.sensor_running = True

    def serial_send_stop_sensing(self):
        """Send the sensorStop command to the sensor to halt sensing
        """
        self._serial_send_command("sensorStop")
        self.sensor_running = False
    
    def _serial_send_command(self,command):
        """Send a given command string over serial

        Args:
            command (str): the command to send to the TI Radar
        """
        successful_send = True

        #send the command over serial
        self.serial_port.write((command+'\n').encode())

        #get the response from the sensor to confirm message was received
        resp = self.serial_port.read_until("mmwDemo:/>").decode('utf-8')
        resp = resp.split("\n")
        resp.reverse()
        resp = " ".join(resp).strip("\r")

        #check to make sure a response was received
        if ("mmwDemo:/>" not in resp) or ("Error" in resp) or ("Exception" in resp):
            self._conn_send_message_to_print("CLI_Controller._serial_send_command: Attempted to send {}, but received {} (expected to receive response with:'mmwDemo:/>')".format(command,resp))
            self._conn_send_error_radar_message()
            successful_send = False

        if self.verbose:
            #print sent command
            self._conn_send_message_to_print("CLI_sent:/>{}".format(command))

            #print received command
            self._conn_send_message_to_print(resp)
        return successful_send

    def _conn_process_Radar_command(self,command:_Message):
        
        match command.type:
            case _MessageTypes.EXIT:
                self.exit_called = True
            case _MessageTypes.START_SENSOR:
                self.serial_send_start_sensing()
            case _MessageTypes.STOP_SENSOR:
                self.serial_send_stop_sensing()
            case _MessageTypes.SEND_CONFIG:
                self.serial_send_config()
            case _MessageTypes.LOAD_NEW_CONFIG:
                self.TI_Radar_config_path = command.value
                self.TI_Radar_config_loaded = True
            case _:
                self._conn_send_message_to_print("CLI_Controller._process_Radar_command: command not recognized")
                self._conn_send_error_radar_message()
        
        #send back command executed message
        self._conn_send_command_executed_message(command.type)
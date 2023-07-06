#python modules
from multiprocessing import Process,Pipe,Queue
from multiprocessing.connection import Connection
from multiprocessing import set_start_method
from _Message import _Message,_MessageTypes
import json
import time
import os
import sys


#TI_RADAR modules
from CLI_Controller import CLIController
from Streamer import Streamer
from Processor import Processor
from ConfigManager import ConfigManager

class Radar:

    def __init__(self,config_file_path):
        """Initialize a new Radar class

        Args:
            config_file_path (str): path to .json config file for Radar
                class and its associated background processes
        """
        set_start_method('spawn')

        #radar_error_detected (called to exit run loop due to ERROR_RADAR)
        self.radar_error_detected = False
        
        #TI radar configuration management
        self._config_file_path = config_file_path

        #get the Radar class configuration as well
        try:
            self.config_Radar = self._parse_json(config_file_path)
        except FileNotFoundError:
            print("Radar.__init__: could not find {} in {}".format(config_file_path,os.getcwd()))
            sys.exit()

        #initialize a configuration manager object
        self.config_manager = ConfigManager()

        #background processes
        self.background_process_classes = [CLIController,Streamer,Processor]
        self.background_process_names = ["CLIController","Streamer","Processor"]
        self.background_processes:list(Process) = []

        #reserve pipes for inter-process communication
        self._conn_CLI_Controller = None
        self._conn_Streamer = None
        self._conn_Processor = None
        #list of background process connections to simplify initialization, starting, and closing of background processes
        self.background_process_connections:list(Connection) = []

        self._prepare_background_processes()

        return
    
    def run(self, timeout = 20):
        """Run the Radar Class

        Args:
            timeout (int, optional): Duration of operation. Defaults to 20.
        """

        #load the radar configuration
        if self.load_TI_radar_configuration() == False:
            print("Radar.run(): experienced error loading config, exiting")
            return

        #start background processes
        if self._start_background_proceses() == False:
            print("Radar.run(): start failed, exiting")
            self.close(nominal_close=False)
            return

        try:
            
            self.start_Radar()

            #start running the sensor
            start_time = time.time()
            while((time.time() - start_time) < timeout) and not self.radar_error_detected:
                #check for updates from each background process
                self._conn_recv_background_process_updates()

                #wait for 10ms before checking again
                time.sleep(10e-3)

            self.close(nominal_close=True)
        except KeyboardInterrupt:
            #join all of the processes, close not needed as background processes automatically close on keyboard interrupt

            #end controller process
            self._join_processes()
    
    def close(self,nominal_close = True):
        """Exit all background processes and stop execution of the Radar class
        """
        if nominal_close:
            #send sensor stop signal
            try:
                self._conn_CLI_Controller.send(_Message(_MessageTypes.STOP_SENSOR))
            except BrokenPipeError:
                print("Radar.close: CLI_Controller was already closed, no STOP_SENSOR message sent")

            #stop streaming
            try:
                self._conn_Streamer.send(_Message(_MessageTypes.STOP_STREAMING))
            except BrokenPipeError:
                print("Radar.close: Streamer was already closed, no STOP_STREAMING message sent")

            #stop processing
            try:
                self._conn_Processor.send(_Message(_MessageTypes.STOP_STREAMING))
            except BrokenPipeError:
                print("Radar.close: Processor was already closed, no STOP_STREAMING message sent")

        #send EXIT commands to processes
        self._conn_send_EXIT_commands()

        #collect any remaining messages
        self._conn_recv_background_process_updates()

        #join the processes
        self._join_processes()

        print("Radar.close: closed successfully")

    def start_Radar(self):
        """Send commands to background radar to start radar streaming and processing
        """
        #load the TI radar config file path into the CLI controller
        self._conn_CLI_Controller.send(_Message(
            type=_MessageTypes.LOAD_NEW_CONFIG,
            value=self.config_manager.TI_radar_config_path
        ))

        #send the configuration to the processor class
        self._conn_Processor.send(_Message(
            type=_MessageTypes.LOAD_NEW_CONFIG,
            value = {"radar_config":self.config_manager.radar_config,
                     "radar_performance":self.config_manager.radar_performance}
        ))
        
        #configure the TI radar via serial
        self._conn_CLI_Controller.send(_Message(_MessageTypes.SEND_CONFIG))

        #wait until configuration sent
        successful_execution = self._conn_wait_for_command_execution(
            conn=self._conn_CLI_Controller,
            command=_MessageTypes.SEND_CONFIG
        )
        if successful_execution:
            #start streaming data
            self._conn_Streamer.send(_Message(_MessageTypes.START_STREAMING))
            
            #start processing data
            self._conn_Processor.send(_Message(_MessageTypes.START_STREAMING))

            #start the radar sensor
            self._conn_CLI_Controller.send(_Message(_MessageTypes.START_SENSOR))
        else:
            self.radar_error_detected = True


## Loading radar configurations
    def load_TI_radar_configuration(self):
        """Load the TI radar configuration in (supports both .json and .cfg file formats), initialize the configuration_manager, generate a .cfg file if needed, and compute radar performance parameters

        Returns:
            bool: True when config loaded successfully, False when config failed to load successfully
        """

        #determine if the provided config is a .json or .cfg
        TI_radar_config_path:str = self.config_Radar["TI_Radar_Config_Management"]["TI_Radar_config_path"]
        
        file_type = TI_radar_config_path.split(".")
        file_type = file_type[-1]
        try:
            match file_type:
                #if .cfg and .json requested, generate JSON
                case "cfg":
                    self.config_manager.load_config_from_cfg(TI_radar_config_path)

                    if self.config_Radar["TI_Radar_Config_Management"]["export_JSON_config"]:
                        self.config_manager.export_config_as_json("generated_config.json")
                #if .json, generate a .cfg
                case "json":
                    self.config_manager.load_config_from_JSON(TI_radar_config_path)

                    self.config_manager.export_config_as_cfg("generated_config.cfg")
                #if neither, configuration error
                case _:
                    print("Radar.load_TI_radar_configuration: {} file type not recognized".format(file_type))
                    return False
            
            #compute radar performance parameters
            self.config_manager.compute_radar_perforance() 

            #check for custom CFAR threshold
            if self.config_Radar["TI_Radar_Config_Management"]["custom_CFAR"]["enabled"]:
                self.config_manager.apply_new_CFAR_threshold(self.config_Radar["TI_Radar_Config_Management"]["custom_CFAR"]["threshold_dB"])

            return True
        except FileNotFoundError:
            print("Radar.load_TI_radar_configuration: Could not find config file")
            return False


##Handling background processes/Multi Processing

    def _prepare_background_processes(self):
        """Prepare all of the background processes and their associated
        connections
        """
                
        #initialize pipes between background processes and Radar class
        self._conn_CLI_Controller, conn_CLI_Controller_child = Pipe()
        self._conn_Streamer,conn_Streamer_child = Pipe()
        self._conn_Processor,conn_Processor_child = Pipe()

        #initialize the lists of connections
        background_process_connection_children = [conn_CLI_Controller_child,conn_Streamer_child,conn_Processor_child]
        
        self.background_process_connections = [
            self._conn_CLI_Controller,
            self._conn_Streamer,
            self._conn_Processor]

        #initialize data pipe between streamer and processor classes
        conn_Processor_data,conn_Streamer_data = Pipe(False)

        for i in range(len(self.background_process_classes)):

            if self.background_process_classes[i] == Streamer:
                data_conn = conn_Streamer_data
            elif self.background_process_classes[i] == Processor:
                data_conn = conn_Processor_data
            else:
                data_conn = None

            self.background_processes.append(
                Process(
                    target=Radar._run_process,
                    args=(
                        self.background_process_classes[i],
                        background_process_connection_children[i],
                        self._config_file_path,
                        data_conn
                    )))
        return

    def _run_process(
            process_class,
            conn:Connection,
            config_file_path,
            data_conn:Connection=None):
        """Run the background process (called when the process
        is started)

        Args:
            process_class (_type_): Class of object to run
            conn (Connection): connection for the object to communicate with the Radar
            config_file_path (_type_): path to JSON config file
            data_conn (Connection, optional): Optional paremeter
                to allow background process to send data to another backgorund
                process. Defaults to None.
        """
        
        #handling CLI controller
        if data_conn==None:
            process_class(conn=conn,config_file_path=config_file_path)
        else:
            process_class(conn=conn,config_file_path=config_file_path,data_connection=data_conn)
        
        return
    
    def _start_background_proceses(self):
        """Starts all background processes

        Returns:
            _type_: True if all processes initialize correctly, False if at least one process failed to initialize
        """

        start_success = True

        for i in range(len(self.background_processes)):

            #start the process
            self.background_processes[i].start()

            #confirm process initialized successfully
            if self._conn_recv_init_status(self.background_process_connections[i]) == False:

                start_success = False
                print("Radar._start_background_processes: {} processes failed to start".format(self.background_process_names[i]))

        return start_success
    
    def _join_processes(self):
        for i in range(len(self.background_processes)):
            self.background_processes[i].join()
            print("Radar._join_processes: {} exited successfully".format(self.background_process_names[i]))

    
### Handle communication between processes
    def _conn_recv_init_status(self, conn:Connection):
        """Receive the initialization status for a given process via a connection to the process. Any other messages received prior to the init status are either printed or not processed

        Args:
            conn (Connection): connection to the process

        Returns:
            bool: True on init success, False on init fail
        """
        
        #receive messages until the init status has been received
        init_received = False
        init_successful = False
        while not init_received:
            msg = conn.recv()

            match msg.type:
                case _MessageTypes.INIT_FAIL:
                    init_received = True
                    init_successful = False
                case _MessageTypes.INIT_SUCCESS:
                    init_received = True
                    init_successful = True
                case _MessageTypes.PRINT_TO_TERMINAL:
                    print(msg.value)
                case _:
                    continue
        
        return init_successful

    def _conn_recv_background_process_updates(self):
        """Receive updates from all of the background processes
        NOTE that COMMAND_EXECUTED messages are ignored
        """

        for i in range(len(self.background_process_connections)):
            conn = self.background_process_connections[i]
            try:
                #process updates while they are available
                while conn.poll():
                    msg = conn.recv()
                    match msg.type:
                        case _MessageTypes.PRINT_TO_TERMINAL:
                            print(msg.value)
                        case _MessageTypes.PRINT_CLEAR_TERMINAL:
                            os.system('cls' if os.name == 'nt' else 'clear')
                        case _MessageTypes.COMMAND_EXECUTED:
                            continue #ignore these commands
                        case _MessageTypes.NEW_DATA:
                            print("Radar._conn_recv_process_updates: NEW_DATA message not currently enabled")
                        case _MessageTypes.ERROR_RADAR:
                            self.radar_error_detected = True
                            print("Radar._conn_recv_background_process_updates: {} sent RADAR error".format(self.background_process_names[i]))
                        case _:
                            continue
            except EOFError:
                print("Radar._conn_recv_background_process_updates: {} was already closed, no message received".format(self.background_process_names[i]))
    
    def _conn_send_EXIT_commands(self):
        """Send Exit commands to each of the background 
        processes so that they close
        """

        for i in range(len(self.background_process_connections)):
            try:
                self.background_process_connections[i].send(_Message(_MessageTypes.EXIT))
            except BrokenPipeError:
                print("Radar._conn_send_EXIT_commands: {} was already closed, no EXIT message sent".format(self.background_process_names[i]))
        return

    def _conn_wait_for_command_execution(self, conn:Connection ,command:_MessageTypes):
        """Waits for a COMMAND_EXECUTED corresponding to the 
        specified command to be received from specified Connection

        Args:
            conn (Connection): connection to the background process  of interest
            command (_MessageTypes): the specific command that is being executed

        Returns:
            bool: True on successful execution, False when not executed correctly
        """
        command_executed = False
       
        try:
            #process updates while they are available
            while not command_executed:
                msg:_Message = conn.recv()
                match msg.type:
                    case _MessageTypes.COMMAND_EXECUTED:
                        if msg.value == command:
                            command_executed = True
                            break
                    case _MessageTypes.PRINT_TO_TERMINAL:
                        print(msg.value)
                        continue
                    case _MessageTypes.ERROR_RADAR:
                        self.radar_error_detected = True
                        print("Radar._conn_wait_for_command_execution: received RADAR error while waiting for command code:{}".format(command))
                        break
                    case _:
                        continue
            return True
        except EOFError:
            print("Radar._conn_wait_for_command_execution: background process was already closed while waiting for command code: {}, no message received".format(command))
            return False


### Other helpful code
    def _parse_json(self,json_file_path):
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

if __name__ == '__main__':
    #create the controller object
    dir_path = os.path.dirname(os.path.realpath(__file__))
    os.chdir(dir_path)
    radar = Radar("config_Radar.json")
    radar.run(timeout=60)
    #Exit the python code
    sys.exit()
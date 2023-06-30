#python modules
from multiprocessing import Process,Pipe,connection,Queue
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

class Radar:

    def __init__(self,config_file_path):
        set_start_method('spawn')

        #radar_error_detected (called to exit run loop due to ERROR_RADAR)
        self.radar_error_detected = False
        
        self._config_file_path = config_file_path

        #background processes
        self.background_process_classes = [CLIController]
        self.background_process_names = ["CLIController"]
        self.background_processes:list(Process) = []

        #reserve pipes for inter-process communication
        self._conn_CLI_Controller = None
        self._conn_Streamer = None
        self._conn_Processor = None
        #list of background process connections to simplify initialization, starting, and closing of background processes
        self.background_process_connections:list(connection.Connection) = []

        self._prepare_background_processes()

        return
    
    def run(self, timeout = 20):

        #start background processes
        if self._start_background_proceses() == False:
            print("Radar.run(): start failed, exiting")
            self.close()
            return

        try:
            
            #configure the radar
            self._conn_CLI_Controller.send(_Message(_MessageTypes.SEND_CONFIG))
            
            #start the radar sensor
            self._conn_CLI_Controller.send(_Message(_MessageTypes.START_SENSOR))

            #start running the sensor
            start_time = time.time()
            while((time.time() - start_time) < timeout) and not self.radar_error_detected:
                #check for updates from each background process
                self._conn_recv_background_process_updates()

                #wait for 10ms before checking again
                time.sleep(10e-3)

            self.close()
        except KeyboardInterrupt:
            #join all of the processes

            #end controller process
            self._join_processes()
    
    def close(self):
        #send sensor stop signal
        self._conn_CLI_Controller.send(_Message(_MessageTypes.STOP_SENSOR))

        #send EXIT commands to processes
        self._conn_send_EXIT_commands()

        #collect any remaining messages
        self._conn_recv_background_process_updates()

        #join the processes
        self._join_processes()

        print("Radar.close: closed successfully")


##Handling background processes/Multi Processing

    def _prepare_background_processes(self):
                
        #initialize pipes between background processes and Radar class
        self._conn_CLI_Controller, conn_CLI_Controller_child = Pipe()
        self._conn_Streamer,conn_Streamer_child = Pipe()
        self._conn_Processor,conn_Processor_child = Pipe()

        #initialize the lists of connections
        background_process_connection_children = [conn_CLI_Controller_child,conn_Streamer_child,conn_Processor_child]
        
        self.background_process_connections = [
            self._conn_CLI_Controller] #,
#            self._conn_Streamer,
#            self._conn_Processor]

        #initialize data pipe between streamer and processor classes
        conn_Streamer_data,conn_Processor_data = Pipe(False)

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
            conn:connection.Connection,
            config_file_path,
            data_conn:connection.Connection=None):
        
        #handling CLI controller
        if data_conn==None:
            process_class(conn=conn,config_file_path=config_file_path)
        else:
            process_class(conn=conn,config_file_path=config_file_path,data_conn=data_conn)
        
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
    def _conn_recv_init_status(self, conn:connection.Connection):
        """Receive the initialization status for a given process via a connection to the process. Any other messages received prior to the init status are either printed or not processed

        Args:
            conn (connection.Connection): connection to the process

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

        for i in range(len(self.background_process_connections)):
            conn = self.background_process_connections[i]
            try:
                #process updates while they are available
                while conn.poll():
                    msg = conn.recv()
                    match msg.type:
                        case _MessageTypes.PRINT_TO_TERMINAL:
                            print(msg.value)
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

        for i in range(len(self.background_process_connections)):
            try:
                self.background_process_connections[i].send(_Message(_MessageTypes.EXIT))
            except BrokenPipeError:
                print("Radar._conn_send_EXIT_commands: {} was already closed, no EXIT message sent".format(self.background_process_names[i]))
        return

    


### Other helpful code
    def _ParseJSON(self,json_file_path):
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
    radar.run(timeout=5)
    #Exit the python code
    sys.exit()
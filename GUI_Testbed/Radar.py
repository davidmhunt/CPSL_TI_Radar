#python modules
from multiprocessing import Process,Pipe,connection
from multiprocessing import set_start_method
from _Message import _Message
import json
import time
import os
import sys


#TI_RADAR modules
from CLI_Controller import CLIController
import Streamer

class Radar:

    def __init__(self,config_file_path):
        set_start_method('spawn')

        self._config_file_path = config_file_path

        #reserve variables for background processes
        self._process_CLI_Controller = None
        self._Streamer = None

        #reserve pipes for inter-process communication
        self._conn_CLI_Controller = None
        self._conn_Streamer = None

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
            self._conn_CLI_Controller.send(_Message(_Message.SEND_CONFIG))
            
            #start the radar sensor
            self._conn_CLI_Controller.send(_Message(_Message.START_SENSOR))

            #start running the sensor
            start_time = time.time()
            while(time.time() - start_time) < timeout:
                #check for updates from each background process
                self._conn_recv_process_updates(self._conn_CLI_Controller)

                #wait for 10ms before checking again
                time.sleep(10e-3)

            self.close()
        except KeyError:
            #join all of the processes

            #end controller process
            self._process_CLI_Controller.join()
            print("Radar.close: CLI controller exited successfully")
    
    def close(self):
        #send sensor stop signal
        self._conn_CLI_Controller.send(_Message(_Message.STOP_SENSOR))

        #send exit signal to each of the background processes
        self._conn_CLI_Controller.send(_Message(_Message.EXIT))
        
        #end controller process
        self._process_CLI_Controller.join()
        print("Radar.close: CLI controller exited successfully")


##Handling background processes/Multi Processing

    def _prepare_background_processes(self):
                
        #initialize inter-process communication
        self._conn_CLI_Controller, conn_CLI_Controller_child = Pipe()


        #prepare each process
        self._process_CLI_Controller = Process(target=Radar._run_CLI_Controller,
                                       args=(conn_CLI_Controller_child,self._config_file_path))
        
        pass

    def _run_CLI_Controller(conn,config_file_path):
        
        #initialize the controller
        CLIController(conn=conn,config_file_path=config_file_path)
    
    def _start_background_proceses(self):

        start_success = True

        #start controller process
        if self._start_background_process(self._process_CLI_Controller,self._conn_CLI_Controller):
            start_success = False
        
        else:
            return start_success

    def _start_background_process(self,process:Process, conn:connection.Connection):
        """Start the given background process and ensure it has initialized correctly

        Args:
            process (Process): The process to start
            conn (connection.Connection): connection to the process

        Returns:
            bool: True on init success, False on init fail
        """
        
        #start the process
        process.start()

        #check for successful init and return the init status
        init_success = self._conn_recv_init_status(conn)

        return init_success
    
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
                case _Message.INIT_FAIL:
                    init_received = True
                    init_successful = False
                case _Message.INIT_SUCCESS:
                    init_received = True
                    init_successful = True
                case _Message.PRINT_TO_TERMINAL:
                    print(msg.value)
                case _:
                    continue
        
        return init_successful

    def _conn_recv_process_updates(self,conn:connection.Connection):

        #process updates while they are available
        while conn.poll():
            msg = conn.recv()
            match msg.type:
                case _Message.PRINT_TO_TERMINAL:
                    print(msg.value)
                case _Message.NEW_DATA:
                    print("Radar._conn_recv_process_updates: NEW_DATA message not currently enabled")
                case _:
                    continue

    


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
    radar.run()
    #Exit the python code
    sys.exit()
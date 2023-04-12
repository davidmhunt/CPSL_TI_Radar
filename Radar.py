from Config import Config
from Processor import Processor
from Streamer import Streamer
import time

class Radar:

    def __init__(
            self,
            config_file_name:str,
            translate_from_JSON = False,
            enable_serial = False,
            CLI_port = "COM4",
            Data_port = "COM5",
            enable_plotting = True,
            jupyter = True,
            data_file = "data_stream.dat",
            refresh_rate = 50.0,
            verbose = False):
        """Initialize the radar class

        Args:
            config_file_name (str): path to the configuration file
            translate_from_JSON (bool, optional): On true, assumes
                the config file is a JSON and translates the 
                JSON to the required format. Defaults to False.
            enable_serial (bool, optional): on True, connect to
                and configure the mmWave device. on False, load raw
                radar samples from data_file and process those
                samples. No serial connections are made when False.
                Defaults to True.
            CLI_port (str, optional): Serial port used for CLI
                (command line interface). Defaults to "COM4".
            Data_port (str, optional): Serial port used for data
                passing. Defaults to "COM5".
            enable_plotting (bool,optional): Generates plots of
                detected points on True. Defaults to False.
            jupyter (bool, optional): On true, uses several specialized
                functions to update plots in real time when using a 
                jupyter notebook. Defaults to True
            data_file (str, optional): file path to the raw serial data file.
                 Defaults to "data_stream.dat".
            refresh_rate (float, optional): Refresh rate in Hz at which
                plots are updated and new data read. Defaults to 50.0.
            verbose (bool, optional): On True, prints extra information
                useful when performing debugging. Defaults to False.
        """
        
        #initialize config class
        self.config = Config(
            config_file_name=config_file_name,
            verbose = verbose,
            translate_from_JSON=translate_from_JSON,
            enable_serial=enable_serial,
            CLI_port=CLI_port,
            Data_port=Data_port
        )

        #initialize processor class
        self.processor = Processor(
            config_parameters=self.config.config_params,
            enable_plotting=enable_plotting,
            plot_heatmap = False,
            jupyter=jupyter,
            verbose=verbose
        )

        #initialize streamer class
        self.streamer = Streamer(
            enable_serial=enable_serial,
            data_file=data_file,
            CLIPort=self.config.CLIport,
            DataPort=self.config.Dataport,
            verbose=verbose,
        )

        #initialize other variables
        self.refresh_delay = 1/refresh_rate
        self.verbose = verbose
        self.serial_enabled = enable_serial

        return
    

    def stream_serial(self):
        """Start a serial stream on the radar, stream in data samples,
        and perform processing as needed
        """

        #start the serial stream
        self.streamer.start_serial_stream()
        packet_available = True
        while True:
            try:
                #read new serial data
                self.streamer.readFromSerial()

                #check for new packet
                packet_available = self.streamer.checkForNewPacket()

                if packet_available:
                    self.processor.performProcessing(self.streamer.currentPacket)

                    #TODO add code for tracking here
                    xyz_vel_coordinates = self.processor.xyz_vel_coordinates
                
                time.sleep(self.refresh_delay)

            except KeyboardInterrupt:
                self.streamer.stop_serial_stream()
                if self.verbose:
                    print("Radar.stream_serial: stopping serial stream")
                break
        return

    def stream_file(self):
        """Stream and process all of the packets/data stored in the data_file
        """
        #variable to keep track of if there are more frames left in the file
        packet_available = True
        while packet_available:
            
            #check for the next packet
            packet_available = self.streamer.checkForNewPacket()

            if packet_available:
                self.processor.performProcessing(self.streamer.currentPacket)

                #TODO add code for tracking here (stored as (4 x N)
                # array where each row contains the [x,y,z,vel] information
                # for each detected point)
                xyz_vel_coordinates = self.processor.xyz_vel_coordinates
            
            time.sleep(self.refresh_delay)
        if self.verbose:
            print("Streamer.stream_file: streaming complete")

        return
    
    def stream(self):
        """perform streaming either from a file or directly with the radar
        over a serial connection
        """
        #start serial stream
        if self.serial_enabled:
            self.stream_serial()
        else:
            self.stream_file()

        return
    

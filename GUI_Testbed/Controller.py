import serial
import time
import json

class Controller:
    """The Radar serial class handles all serial communications between 
    """

    def __init__(
            self,
            config_file_name,
            translate_from_JSON = False,
            CLI_port = "COM4",
            enable_serial = True,
            verbose = False):
        """Initialize the Config class

        Args:
            config_file_name (_type_): path to the configuration file
            translate_from_JSON (bool, optional): On true, assumes
                the config file is a JSON and translates the 
                JSON to the required format. Defaults to False.
            CLI_port (str, optional): Serial port used for CLI
                (command line interface). Defaults to "COM4".
            enable_serial (bool, optional): on True, connect to
                and configure the mmWave device. Defaults to True.
            verbose (bool, optional): on True, prints out relevant
                information. Defaults to False.
        """
        #initialize verbose settings
        self.verbose = verbose

        #load the configuration file
        self.config = []
        if translate_from_JSON:
            if self.verbose:
                print("Config.__init__: translating config file from JSON")
            self.config = self.translateFromJSON(config_file_name)
        else:
            self.config = [line.rstrip('\r\n') for line in open(config_file_name)]
        
        #load the configuration parameters
        self.config_params = {}
        self.parseConfigFile()

        #send the configuration to the device
        self.serial_enabled = enable_serial
        self.CLIport = None
        self.Dataport = None
        if enable_serial:

            #initialize the serial ports
            self.CLIport = serial.Serial(CLI_port, 115200)

            #send to the device
            self.sendConfigSerial()

        return
    
    def translateFromJSON(self,JSONFileName):
        """Translates the JSON input file into the desired configuration format 
        """
        f = open(JSONFileName)
        content = ''
        for line in f: 
            content += line
        JSONconfig = json.loads(content)
        return self.create_config(JSONconfig)
        
        
    def get_JSON_data(self, dump, root=True):
        """Recursively decomposes the input data in the JSON entry to produce a command in the desired format
        """  
        value = ''
        if type(dump) in (dict,):
            for key in dump:
                item = dump[key]
                if root:
                    if '|' in key: key = key[:-key[::-1].index('|') - 1]  
                    value += '\n{} '.format(key)
                value += self.get_JSON_data(item, False)
        elif type(dump) in (list, tuple,):
            value += '{} '.format(''.join([self.get_JSON_data(v, False) for v in dump]))
        else:
            if dump is not None:
                value += '{} '.format(dump)
        return value

    def create_config(self, cfg=None): 
        """Add appropriate start and end commands to the configuration
        """ 
        post = ('sensorStop',) + ('flushCfg',) + tuple(self.get_JSON_data(cfg).split('\n')[1:][2:]) + ('sensorStart',)        
        return post


    def sendConfigSerial(self):
        """Send the configuration to the mmWave radar, but do not start sensor operation
        """

        #read the configuration and send it to the device
        for i in self.config:
            if(i != "sensorStart"):
                
                #send the command
                self.CLIport.write((i+'\n').encode())

                #wait for 0.05 s for the command to be sent
                time.sleep(0.07)

                #get the response from the sensor to confirm message was received
                resp = self.CLIport.read(self.CLIport.in_waiting).decode('utf-8')
                #resp = resp.strip().split('\n').reverse()
                #resp = " ".join(resp)
                if self.verbose:
                    print("Config.sendConfigSerial: sent '{}'".format(i))
                    print("Config.sendConfigSerial: received '{}'".format(resp))
            #special behavior for sensorStart command
            elif (i == "sensorStart"):
                if self.verbose:
                    print("Config.sendConfigSerial: 'sensorStart' in config file. Skipping sensorStart command")
            
            #sleep before sending next command
            time.sleep(0.01)       
        
        return
    
    def parseConfigFile(self): # method to parse and store necessary configuration parameters for future calculations/reference
        """Parses the config file stored in self.config and saves key configuration information in self.config_params
        """
        
        # Read the configuration file and send it to the board
        for i in self.config:
            
            # Split the line
            splitWords = i.split(" ")
            
            # Hard code the number of antennas, change if other configuration is used
            numRxAnt = 4
            numTxAnt = 2
            
            # Get the information about the profile configuration
            if "profileCfg" in splitWords[0]:
                startFreq = int(float(splitWords[2]))
                idleTime = int(splitWords[3])
                rampEndTime = float(splitWords[5])
                freqSlopeConst = float(splitWords[8])
                numAdcSamples = int(splitWords[10])
                numAdcSamplesRoundTo2 = 1
                
                while numAdcSamples > numAdcSamplesRoundTo2:
                    numAdcSamplesRoundTo2 = numAdcSamplesRoundTo2 * 2
                    
                digOutSampleRate = int(splitWords[11])
                
            # Get the information about the frame configuration    
            elif "frameCfg" in splitWords[0]:
                chirpStartIdx = int(splitWords[1])
                chirpEndIdx = int(splitWords[2])
                numLoops = int(splitWords[3])
                numFrames = int(splitWords[4])
                framePeriodicity = int(splitWords[5])

        #save the configuration information in a dictionary
        numChirpsPerFrame = (chirpEndIdx - chirpStartIdx + 1) * numLoops
        self.config_params["numDopplerBins"] = numChirpsPerFrame / numTxAnt
        self.config_params["numRangeBins"] = numAdcSamplesRoundTo2
        self.config_params["rangeResolutionMeters"] = (3e8 * digOutSampleRate * 1e3) / (2 * freqSlopeConst * 1e12 * numAdcSamples)
        self.config_params["rangeIdxToMeters"] = (3e8 * digOutSampleRate * 1e3) / (2 * freqSlopeConst * 1e12 * self.config_params["numRangeBins"])
        self.config_params["dopplerResolutionMps"] = 3e8 / (2 * startFreq * 1e9 * (idleTime + rampEndTime) * 1e-6 * self.config_params["numDopplerBins"] * numTxAnt)
        self.config_params["maxRange"] = (300 * 0.9 * digOutSampleRate)/(2 * freqSlopeConst * 1e3)
        self.config_params["maxVelocity"] = 3e8 / (4 * startFreq * 1e9 * (idleTime + rampEndTime) * 1e-6 * numTxAnt)
        
        return
    
    def close_serial(self):
        """Close the serial ports
        """
        if self.serial_enabled:
            #close Data serial port
            if self.Dataport.is_open:
                self.Dataport.close()
            if self.CLIport.is_open:
                self.CLIport.close()
            
            if self.verbose:
                print("Config.close_serial: serial ports closed")

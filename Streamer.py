import serial
import time
import numpy as np
from Processor import Processor


# Streamer class -> use either loadFile + readFromFile (in a loop w/ delays) OR readRealTime (also must be in a loop with delays). Both read methods will return the next packet available, if there is one

class Streamer:

    def __init__(self,
                 enable_serial=False,
                 data_file = "data_stream.dat",
                 CLIPort:serial.Serial =None,
                 DataPort:serial.Serial =None,
                 verbose = False):
        """Initialize the streamer class

        Args:
            enable_serial (bool, optional): On True, streams data from the radar. 
                On False, reads data from data_file and processes the 
                read data. Defaults to False.
            data_file (str, optional): file path to the raw serial data file.
                 Defaults to "data_stream.dat".
            CLIPort (serial.Serial, optional): serial.Serial object used to send
                commands to the radar. Defaults to None.
            DataPort (serial.Serial, optional): serial.Serial object used to read
                raw data from the radar. Defaults to None.
            verbose (bool, optional): On True, prints debugging information. Defaults to False.
        """

        #save verbose setting
        self.verbose = verbose

        #initialize the byte buffer
        maxBufferSize = 2**18
        self.byteBuffer = np.zeros(maxBufferSize,dtype = 'uint8')
        self.byteBufferLength = 0

        #initialize the packet buffer
        self.currentPacket = np.empty(0)

        #configure the serial ports
        self.CLIport = CLIPort
        self.DataPort = DataPort

        #load data in from a file if read_from_file is true
        self.serial_enabled = enable_serial
        if not self.serial_enabled:
            self.loadFile(data_file)
        
        return

        
    def loadFile(self,data_file): 
        """Import raw serial data saved in a local file

        Args:
            data_file (str): file path to the raw serial data file
        """
        byteVec = np.fromfile(data_file, dtype="byte")
        self.updateBuffer(byteVec)

        if self.verbose:
            print("Streamer.loadFile: Loaded data from {}".format(data_file))
        return

    def readFromSerial(self): 
        """Reads in any waiting data and adds it to the buffer

        Returns:
            _type_: _description_
        """
        readBuffer = self.DataPort.read(self.DataPort.in_waiting)
        byteVec = np.frombuffer(readBuffer, dtype = 'uint8')
        self.updateBuffer(byteVec)
        return

    def updateBuffer(self, byteVec): 
        """Update ByteBuffer by append byteVec to the end

        Args:
            byteVec (np.array(dtype='uint8')): buffer with data 
                read from the data serial port
        """
        maxBufferSize = 2**18
        byteCount = len(byteVec)

        # add the data to the end of the buffer, update buffer length
        if (self.byteBufferLength + byteCount) < maxBufferSize:
            self.byteBuffer[self.byteBufferLength:self.byteBufferLength + byteCount] = byteVec[:byteCount]
            self.byteBufferLength = self.byteBufferLength + byteCount
        else:
            print("Streamer.updateBuffer: Buffer is full")
        
        return

    def checkForNewPacket(self): 
        """Check for a new packet. If a new packet is detected,
             update self.currentPacket and return True to note 
             that a new packet was detected

        Returns:
            bool: True if new packet was detected
        """
        #magic word for detecting packet start
        magicWord = [2, 1, 4, 3, 6, 5, 8, 7]

        # word array to convert 4 bytes to a 32 bit number
        word = [1, 2**8, 2**16, 2**24]

        # Check that the buffer has some data
        if self.byteBufferLength > 16:
            
            # Check for all possible locations of the magic word
            possibleLocs = np.where(self.byteBuffer == magicWord[0])[0]

            # Identify all possible packet start locations (all of the places that the magic word occurs in)
            startIdx = []
            for loc in possibleLocs:

                #get the possible magic word
                check = self.byteBuffer[loc:loc+8]

                #check to make sure that the magic word matches
                if np.all(check == magicWord):
                    startIdx.append(loc)
                
            # Check that startIdx is not empty
            if startIdx:
                
                #check to make sure that the packet is a valid packet
                packet_start_i = 0
                for i in range(len(startIdx)-1): 
                    #TODO: added code to check for the case of only partially received packets or corrupt packets
                    packet_start_i = i
                    stated_packetLen = np.matmul(self.byteBuffer[startIdx[i] + 12:startIdx[i] + 12+4],word)

                    actual_packetLen = startIdx[i + 1] - startIdx[i]

                    if stated_packetLen == actual_packetLen:
                        break


                    #check that the total packet length matches the 
                # Remove the data before the first start index
                if startIdx[packet_start_i] > 0 and startIdx[packet_start_i] < self.byteBufferLength:
                    self.byteBuffer[:self.byteBufferLength-startIdx[packet_start_i]] = self.byteBuffer[startIdx[packet_start_i]:self.byteBufferLength]

                    self.byteBuffer[self.byteBufferLength-startIdx[packet_start_i]:] = np.zeros(len(self.byteBuffer[self.byteBufferLength-startIdx[packet_start_i]:]),dtype = 'uint8')

                    self.byteBufferLength = self.byteBufferLength - startIdx[packet_start_i]
                
                
                # Read the total packet length
                totalPacketLen = np.matmul(self.byteBuffer[12:12+4],word)

                # Check that all the packet has been read
                if (self.byteBufferLength >= totalPacketLen) and (self.byteBufferLength != 0):

                    #extract the current packet (hard copy so that data not over-written in next steps)
                    self.currentPacket = self.byteBuffer[:totalPacketLen].copy()

                    #remove the current packet from the buffer
                    self.byteBuffer[:self.byteBufferLength - totalPacketLen] = self.byteBuffer[totalPacketLen:self.byteBufferLength] 

                    #add zeros where the packet previously was
                    self.byteBuffer[self.byteBufferLength - totalPacketLen:] = np.zeros(len(self.byteBuffer[self.byteBufferLength - totalPacketLen:]),dtype = 'uint8') 

                    #update current buffer length
                    self.byteBufferLength = self.byteBufferLength - totalPacketLen

                    #return True to note that a new packet was detected
                    return True
        else:
            #return False to note that no new packet was detected
            return False

    def start_serial_stream(self):
        """Start a serial stream
        """
        self.CLIport.write(('sensorStart\n').encode())
        if self.verbose:
            print("Streamer.start_serial_stream: sent 'sensorStart'")
            
            #wait for 0.07 s for the command to be sent
            time.sleep(0.07)

            #get the response from the sensor to confirm message was received
            resp = self.CLIport.read(self.CLIport.in_waiting).decode('utf-8')
            print("Streamer.start_serial_stream: received '{}'".format(resp))

    def stop_serial_stream(self):
        """Stop the serial stream
        """
        self.CLIport.write(('sensorStop\n').encode())
        if self.verbose:
            print("Streamer.stop_serial_stream: sent 'sensorStop'")
            
            #wait for 0.07 s for the command to be sent
            time.sleep(0.07)

            #get the response from the sensor to confirm message was received
            resp = self.CLIport.read(self.CLIport.in_waiting).decode('utf-8')
            print("Streamer.stop_serial_stream: received '{}'".format(resp))
        
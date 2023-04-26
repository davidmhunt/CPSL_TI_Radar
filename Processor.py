import numpy as np
import matplotlib.pyplot as plt
from matplotlib import style
from matplotlib.pyplot import plot, show
from IPython.display import display, clear_output

# Processing class -> takes in a packet and configuration data, returns detected objects, x y z coordinates

class Processor:
    
    def __init__(self,
                 config_parameters,
                 enable_plotting = False,
                 plot_heatmap = False,
                 jupyter = True,
                 verbose = False):
        """Initialize the Processor Class

        Args:
            config_parameters (dict): dictionary containing radar 
                configuration information
                generated from the Config class
            enable_plotting (bool,optional): Generates plots of
                detected points on True. Defaults to False.
            jupyter (bool, optional): On true, uses several specialized
                functions to update plots in real time when using a 
                jupyter notebook. Defaults to True
            verbose (bool, optional): Prints out extra information on 
                True. Defaults to False.
            
        """
        #initialize verbose settings
        self.verbose = verbose

        #initialize the configuration parameters
        self.config_params = config_parameters

        #initialize the array to store the detected objects
        self.detected_objects = {}
        self.xyz_vel_coordinates = np.zeros(shape=(50,4))

        #initialize the array to store the heatmap
        self.heatmap = np.zeros(self.config_params["numRangeBins"] * 8, dtype=np.complex_)

        #initialize plotting
        self.plotting_enabled = enable_plotting
        self.plot_heatmap = plot_heatmap
        self.jupyter = jupyter
        self.hdisplay = None #display handle for jupyter notebooks
        self.fig = None
        self.axs = []
        if enable_plotting:
            if self.jupyter:
                self.hdisplay = display("",display_id=True)
            self.fig, new_ax = plt.subplots(1)
            self.axs.append(new_ax)
            plt.title("Detected Points")
            plt.xlabel("X Coordinate (m)")
            plt.ylabel("Y Coordinate (m)")
            
        return

    def decodePacket(self,Packet):
        """Decodes the given data packet

        Args:
            Packet (np.array(dtype = uint8)): packet containing the
                data to be processed
        """

        # Constants
        MMWDEMO_UART_MSG_DETECTED_POINTS = 1

        #TODO: added these even though we aren't actually using these
        MMWDEMO_UART_MSG_RANGE_PROFILE   = 2
        MMWDEMO_UART_MSG_RANGE_AZIMUTH_HEATMAP   = 4
        MMWDEMO_UART_MSG_RANGE_DOPPLAR_HEATMAP   = 5
    
        header,idX = self.decodePacketHeader(Packet)
        
        # Read the TLV messages
        for tlvIdx in range(header["numTLVs"]):
            
            # word array to convert 4 bytes to a 32 bit number
            word = [1, 2**8, 2**16, 2**24]

            # Check the header of the TLV message
            tlv_type = np.matmul(Packet[idX:idX+4],word)
            idX += 4
            tlv_length = np.matmul(Packet[idX:idX+4],word)
            idX += 4

            if self.verbose:
                print("Processor.decodePacket: TLV Type: {}".format(tlv_type))
                print("Processor.decodePacket: TLV Length: {}".format(tlv_length))
            
            # Read the data depending on the TLV message
            word = [1, 2**8]
            if tlv_type == MMWDEMO_UART_MSG_DETECTED_POINTS:

                # word array to convert 4 bytes to a 16 bit number
                tlv_numObj = np.matmul(Packet[idX:idX+2],word)
                idX += 2
                tlv_xyzQFormat = 2**np.matmul(Packet[idX:idX+2],word)
                idX += 2
                
                # Initialize the arrays
                rangeIdx = np.zeros(tlv_numObj,dtype = 'int16')
                dopplerIdx = np.zeros(tlv_numObj,dtype = 'int16')
                peakVal = np.zeros(tlv_numObj,dtype = 'int16')
                x = np.zeros(tlv_numObj,dtype = 'int16')
                y = np.zeros(tlv_numObj,dtype = 'int16')
                z = np.zeros(tlv_numObj,dtype = 'int16')
                
                for objectNum in range(tlv_numObj):
                    
                    # Read the data for each object
                    rangeIdx[objectNum] =  np.matmul(Packet[idX:idX+2],word)
                    idX += 2
                    dopplerIdx[objectNum] = np.matmul(Packet[idX:idX+2],word)
                    idX += 2
                    peakVal[objectNum] = np.matmul(Packet[idX:idX+2],word)
                    idX += 2
                    x[objectNum] = np.matmul(Packet[idX:idX+2],word)
                    idX += 2
                    y[objectNum] = np.matmul(Packet[idX:idX+2],word)
                    idX += 2
                    z[objectNum] = np.matmul(Packet[idX:idX+2],word)
                    idX += 2
                    
                # Make the necessary corrections and calculate the rest of the data
                rangeVal = rangeIdx * self.config_params["rangeIdxToMeters"]
                dopplerIdx[dopplerIdx > (self.config_params["numDopplerBins"]/2 - 1)] = dopplerIdx[dopplerIdx > (self.config_params["numDopplerBins"]/2 - 1)] - 65535
                dopplerVal = dopplerIdx * self.config_params["dopplerResolutionMps"]
                
                #TODO These were in the original code, but did we need these (K note - handles overflow case, not sure if we want?)
                #x[x > 32767] = x[x > 32767] - 65536
                #y[y > 32767] = y[y > 32767] - 65536
                #z[z > 32767] = z[z > 32767] - 65536
                
                x = x / tlv_xyzQFormat
                y = y / tlv_xyzQFormat
                z = z / tlv_xyzQFormat
                
                # Store the data in the detObj dictionary
                self.detected_objects = {"numObj": tlv_numObj, "rangeIdx": rangeIdx, "range": rangeVal, "dopplerIdx": dopplerIdx, \
                        "doppler": dopplerVal, "peakVal": peakVal, "x": x, "y": y, "z": z}
                
                #generate an array of x,y,z,velocity coordinates for each object
                self.xyz_vel_coordinates = np.array(
                    [self.detected_objects['x'],
                     self.detected_objects['y'],
                     self.detected_objects['z'],
                     self.detected_objects['doppler']]
                ).transpose()

            if self.verbose:
                print("Processor.decodePacket: detected_object {}".format(self.detected_objects))
                print("Processor.decodePacket: xyz_vel_coordinates {}".format(self.xyz_vel_coordinates))
            #TODO: was in previous python script
            
            if tlv_type == MMWDEMO_UART_MSG_RANGE_AZIMUTH_HEATMAP: 
                for i in range(int(tlv_length/4)):
                    self.heatmap[i] = complex(np.matmul(Packet[idX+2:idX+4],word),np.matmul(Packet[idX:idX+2],word)) # formatted im, re
                    idX +=4; 

        if self.verbose:
            print("Processor.Streamer: Finished Processing Packet\n")
        
        return

    def decodePacketHeader(self,Packet):
        # word array to convert 4 bytes to a 32 bit number
        word = [1, 2**8, 2**16, 2**24]
        
        # Initialize the pointer index
        idX = 0
        
        # Read the header
        header = {}
        header["magicNumber"] = Packet[idX:idX+8]
        idX += 8

        header["version"] = format(np.matmul(Packet[idX:idX+4],word),'x')
        idX += 4

        header["totalPacketLen"] = np.matmul(Packet[idX:idX+4],word)
        idX += 4

        header["platform"] = format(np.matmul(Packet[idX:idX+4],word),'x')
        idX += 4

        header["frameNumber"] = np.matmul(Packet[idX:idX+4],word)
        idX += 4

        header["timeCpuCycles"] = np.matmul(Packet[idX:idX+4],word)
        idX += 4

        header["numDetectedObj"] = np.matmul(Packet[idX:idX+4],word)
        idX += 4

        header["numTLVs"] = np.matmul(Packet[idX:idX+4],word)
        idX += 4

        if self.verbose:
            print("Procesor.decodePacketHeader: {}".format(header))
        
        return header,idX

    def update_plots(self):
        """Update the plots with the current set of detected points
        from self.detected_objects
        """
        #get x and y coordinates for plotting
        x = self.detected_objects.get('x')
        y = self.detected_objects.get('y')

        #plot the data
        plt.tight_layout()
        self.axs[0].cla()
        self.axs[0].scatter(x,y)
        self.axs[0].set_title("Detected Points")
        self.axs[0].set_xlabel("X Coordinate (m)")
        self.axs[0].set_ylabel("Y Coordinate (m)")
        self.axs[0].set_xlim((-10,10))
        self.axs[0].set_ylim((0,10))
        #plt.show()

        #plot the data
        if (self.plot_heatmap):
            self.axs[1].cla()
            disp= self.heatmap.reshape(self.config_params["numRangeBins"], 8)
            self.axs[1].imshow(abs(disp), cmap='hot')
            self.axs[1].set_title("Heatmap")
            self.axs[1].set_xlim((0, 8))


        #special code for jupyter notebooks
        if self.jupyter:
            self.hdisplay.update(self.fig)
        return

        
    
    def performProcessing(self,Packet):
        """Decodes the given data packet

        Args:
            Packet (np.array(dtype = uint8)): packet containing the
                data to be processed

        Returns:
            dict: Dictionary containing information about each 
                detected object
        """

        self.decodePacket(Packet)

        if self.plotting_enabled:
            self.update_plots()
        
        return self.detected_objects
    


    
    
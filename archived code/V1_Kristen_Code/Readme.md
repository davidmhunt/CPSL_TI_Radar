**README**

**Top-level Folder:** TI\_Radar\_Demo\_Visualizer

**Necessary Installations Required:** TI MMWAVE-SDK 2.1.0

**Hardware Required:** TI IWR1443 Radar

**Classes + Structure:**

- _Config.py_
- _Processor.py_
- _Streamer.py_
- _Radar.py_
- Jupyter Notebook: _demo.ipynb_

![alt text](https://github.com/davidmhunt/TI_Radar_Demo_Visualizer/blob/klangell-patch-1/class_organization_diagram.png?raw=true)


**Configurations Folder:** TI\_Radar\_Demo\_Visualizer/configurations 

- Contains files in both JSON and demo visualizer configuration formats

**Raw Data Samples Folder:** TI\_Radar\_Demo\_Visualizer/raw\_data\_samples

- Contains .dat files of data collected from Demo Visualizer

**How to run:**

See "demo.ipynb" Jupyter Notebook

Identify correct serial ports:

- Windows: In Device Manager locate XDS110 Class Application/User UART and XDS110 Class Auxiliary Data ports
- Linux: Use command ls /dev/ttyACM\*, if access denied use "sudo usermod -a -G dialout $USER"

In script, initialize Radar class:

- Provide configuration file name

"configurations/FILENAME.cfg"

- Enable translate\_from\_JSON if using JSON configuration
- If using a data file instead of live data, provide the correct data file path "raw\_data\_samples/FILENAME.dat"
- Ensure that the configuration file matches the configuration the data was collected on!
- Assign serial ports -\> CLI\_port for configuration and Data\_port for receiving data
- Enable enable\_plottingif plots are desired

Call radar.stream()

**Detailed Functionalities/Descriptions:**

_Config.py Class_

- Executes upon initialization of class.
- Extract the configuration from the JSON file (translateFromJSON()/get\_JSON\_data() methods recursively create config file in correct format) OR read configuration from correctly formatted demo visualizer configuration.
- Parse the configuration (parseConfigFile() method) to extract relevant configuration parameters (for example, numRangeBins), and store them in a dictionary.
- If serial enabled, initialize the serial ports, and send the configuration data to the device (sendConfigSerial() method). Then, close the serial ports (close\_serial() method).
- Notes: class is complete, no future development in plans.

_Configurations_

- There are two formats in which configurations can be specified: JSON and demo-visualizer-generated configurations.
- The initial JSON (jsonconfig.cfg) has a configuration which enables basic functionality, and enables the reporting of detected objects and their locations. The JSON file allows for the easy tuning of low-level parameters not present in the demo visualizer.
- The demo visualizer GUI, alternatively, allows for the high-level tuning of parameters, based on maximum ranges/velocities and resolutions desired. Utilizing the correct radar and SDK version (2.1), input the desired "scene selection." Use the "save config to PC" button to generate a new config that can be directly sent to the radar. The configuration "1443config.cfg" is an example of this configuration.

_Streamer.py Class_

- Contains methods to load data from the provided file (loadFile() method), or read live data from the serial ports (readFromSerial() method). Both read as bytes.
  - In either case, upon obtaining new data, updates a global FIFO byte buffer (of size 218 bytes) with updateBuffer() method
- Contains method checkForNewPacket(). First, it checks for a new packet within the byte buffer. Looks for magic words (indicates start of a new packet), finds locations of magic words. Reads length of the packet. Then, extracts the entire next available packet (in FIFO order) from the buffer.
- The next available packet is stored as the current packet of the streamer.
- Notes: mostly complete.

_Raw\_Data\_Samples_

- Data recorded from the Demo Visualizer, which can be processed offline by our script.
- If the data sample is very large, maximum buffer size adjustment may be necessary.

_Processor.py Class_

- This class processes individual packets (decodePacket() method). The format of the packet is specified in this documentation: [https://e2e.ti.com/cfs-file/\_\_key/communityserver-discussions-components-files/1023/mmw-Demo-Data-Structure\_5F00\_8\_5F00\_16.pdf](https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/1023/mmw-Demo-Data-Structure_5F00_8_5F00_16.pdf)
- The packet header is decoded first (decodePacketHeader() method), providing the total packet length, number of TLVs, etc. An index is established to keep track of the current place in the packet as we process it.
- Then, the rest of the packet is decoded by looping over all the TLVs in the packet. The packet contains all of the data enabled in the configuration file via the "guiMonitor" parameter. Each TLV has a type, indicating the type of data it contains: Detected Objects = 1, Range Profile = 2, Noise Profile = 3, Range Azimuth Heatmap = 4, Range Doppler Heatmap = 5, Statistics = 6.
- Currently we have implemented processing for the Detected Objects and the Range Azimuth Heatmap (TLV types 1, 4).
- The correct data is extracted from both the header and each TLV following the format provided in the TI PDF guide.
- Contains the update\_plots() method to create plots for both the detected objects and the range azimuth heatmap (in progress!).
- Notes: most room for development in this class. Ideally, we would like to implement processing and plot generation for all of the TLV types. Heatmap plot generation is still in progress. Data has been correctly recorded, but to generate the plot an additional FFT across each range bin must be taken.

Miscellaneous Links:

- Demo Visualizer Link: [https://dev.ti.com/gallery/view/mmwave/mmWave\_Demo\_Visualizer/ver/2.1.0/](https://dev.ti.com/gallery/view/mmwave/mmWave_Demo_Visualizer/ver/2.1.0/)
- Demo Visualizer User Guide:

[https://www.ti.com/lit/ug/swru529c/swru529c.pdf?ts=1682496741483](https://www.ti.com/lit/ug/swru529c/swru529c.pdf?ts=1682496741483)

#

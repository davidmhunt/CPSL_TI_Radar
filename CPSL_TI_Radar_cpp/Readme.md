# CPSL_TI_RADAR C++ code

## Installation

### Pre-requisite packages
Before building and installing this package, you must first have the following software installed:
1. C++ compiler (supporting at least C++ 11)
2. C++ boost libraries
3. CMake

The following installation instructions will work for linux devices, but should be similar for Windows and Mac devices as well.

#### 1. Install C++ compiler
1. First check to see if c+ is installed by running the following command
```
g++ --version
```
If this returns at least version 4.8.1, you can move onto the next step

2. If you don't have c++ installed or if your c++ version is out of date, run the following command to install c++ (for linux).
```
sudo apt update
sudo apt install build-essential
```

#### 2. Install boost libraries
1. Next, check to see if the C++ boost libraries are installed on your system. To do this, run the following command (in linux):
```
dpkg -s libboost-dev | grep Version
```

2. If you don't have the boost libraries installed, run the following command to install the requisite packages (for debian based systems including Ubuntu)
```
sudo apt update
sudo apt install libboost-all-dev
```

#### 3. Install CMake
1. Next, confirm that CMake is installed. To do this, run the following command:
```
cmake --version
```
2. If it isn't installed, run the following command to install it (for debian based systems including ubuntu)
```
sudo apt update
sudo apt install cmake
```

#### 4. Allow access to serial ports
1. Finally, to ensure that your system has access to the serial ports to connect to the radar, run the following command
```
sudo usermod -a -G dialout $USER
```
2. To allow the command to take effect, simply reboot or log out and then log back in on your system

## Building CPSL_TI_Radar_cpp

To download, build, and install the CPSL_TI_Radar c++ code, perform the following instructions:
1. Clone the repository
```
git clone --recurse-submodules https://github.com/davidmhunt/CPSL_TI_Radar
```

If you forgot to perform the --recurse-submodules when cloning the repository, you can use the following command to load the necessary submodules
```
git submodule update --init --recursive
```

2. Next build and make the project
```
cd CPSL_TI_Radar/CPSL_TI_Radar_cpp
cd build
cmake ../
cmake --build .
```

## Preparing your hardware

To stream samples from the DCA1000, the following steps must be completed
1. Configure your machine's I.P address for the DCA1000
2. Flash the correct firmware onto the IWR1443

### 1.Setup Static IP Address
On your machine, configure the TCP/IPv4 to have the following settings:
1. Static IP Address
2. IP address: 192.168.33.30
3. Subnet mask: 255.255.255.0

### 2.Flash the correct firmware onto the device
To flash the correct firmware onto the IWR1443, you will need the UNIFLASH tool from Texas Instruments. Start by downloading the correct version of the tool from the [downloads page](https://www.ti.com/tool/UNIFLASH#downloads). Next, follow the instructions below corresponding to the board that you are using.

#### [IWR1443] DCA Streaming
1. Power off the IWR1443, and place it into Flashing Mode mode. Refer to the following diagram for placing the IWR in flashing mode ![IWR_SOP_Modes](../CPSL_TI_Radar/readme_images/IWR_SOP_modes.png)
3. Use the Uniflash tool to install the binary located in the [firmware folder](../Firmware/DCA1000_Streaming). Make sure you use the firmware in the IWR_Demos folder if streaming data directly from the IWR

#### [IWR1443] IWR Streaming
1. Power off the IWR1443, and place it into Flashing Mode mode. Refer to the following diagram for placing the IWR in flashing mode ![IWR_SOP_Modes](../CPSL_TI_Radar/readme_images/IWR_SOP_modes.png)
3. Use the Uniflash tool to install the mmWave SDK found as part of the [TI mmWave SDK 2.01.00.04](https://www.ti.com/tool/download/MMWAVE-SDK/02.01.00.04)

#### [IWR1843] DCA Streaming and IWR Demos
1. Power off the IWR1843, and place it into Flashing Mode mode. Refer to the following diagram for placing the IWR in flashing mode ![IWR1843_Modes](../CPSL_TI_Radar/readme_images/IWR1843_SOP_nodes.png)
2. For the IWR1843 (or any radar that can run the mmWave SDK boost, you should be able to load the default "demo" firmware provided by TI onto the board to stream samples to the DCA1000 board.)

    a.We developed this pipeline using mmWave 3.6. Using a different pipeline may require slight changes in the code.
    b. NOTE: additional documentation on the demo firmware can be found in the index.html file located in (ti/mmwave_sdk_03_06_02_00-LTS/packages/ti/demo/xwr18xx/mmw/docs/doxygen/html)


Once the correct firmware is flashed onto your board, power cycle the board and place it into functional mode.

## Running

To run the cpp code, perform the following:
1. update the .json config file
2. remake the project
3. run the c++ code

### 1. Updating the .json config files

The CPSL_TI_Radar_cpp code utilizes .json files to load essential configuration information. All of the configuration files can be found in the [configs](./configs/) folder. Here, the essential components of each configuration are as follows 


#### TI_Radar_Config_management
* TI_Radar_config_path: specifies the path to the IWR's .cfg file. Example files are located in the [configurations](../configurations/) folder. Be sure the choose the one corresponding to either the DCA1000, or the IWR Demo depending on your use case. 

    * Note: If using the mmWave SDK demos (ex: SDK3.5) with the DCA1000 and IWR1843 boost boards, make sure that the lvdsStreamCfg is correctly set (see the mmWave sdk documentation). For example, a viable lbdsStreamCfg setting is featured below. To just stream the ADC samples only, use the following command (disables SW streaming)

    ```
    lvdsStreamCfg -1 0 1 0 
    ```

    To stream all available data use this command instead (will require additional processing/streaming time to support this though)

    ```
    lvdsStreamCfg -1 1 1 1
    ```

    ### Notes:
    1. Due to the uncertain interleaving behavior with IWR's operating with SDK3+, please use an even number of samples for configurations with only a single rx, and only use configurations with 1,2, or 4 receivers.

#### CLI_Controller
* CLI_port: the address to the serial port used to program the IWR device. If you don't know the serial port, use the [determine_serial_ports.ipynb](../utilities/determine_serial_ports.ipynb) notebook to determine them. Usually the CLI port is the smaller number.

#### Streamer
This part of the JSON file determines where the data is coming from. Only one of the two options should be enabled.
* serial_streaming: use this when streaming directly from the IWR demo application
* DCA1000_streaming: use this when streaming from the DCA1000
* save_to_file: when set to True, this will save the raw ADC data cube information for each frame to a .bin file which can be utilized at a later
#### Processor: 
This part is currently not utilized when streaming DCA1000 data


#### ROS/Listeners:
If using ROS nodes to connect to the Radar code, set this to true. Otherwise set it to false. To make it easier to receive the data, we provide several starter ROS nodes in associated [CPSL_TI_Radar_ROS Repository](https://github.com/davidmhunt/CPSL_TI_Radar_ROS)

### 2. Radar .cfg file

Several sample .cfg files are located in the [configurations](../configurations/) folder. For generating additional configurations, we recommend using the [TI mmWave Demo Visualizer](https://dev.ti.com/gallery/view/mmwave/mmWave_Demo_Visualizer/ver/2.1.0/). There, you can specify settings, and then use the "Save config to PC" button to download a configuration. To fully understand the configurations, please refer to the mmWave sdk documentation. 
* To understand a particular configuration, there are a few helpful notebooks located in the [utilities_and_notebooks](../utilities/) folder including the [print_config](../utilities/print_config.ipynb) notebook which will decode the config and list the key parameters. 


### 2. Remake the project

To be safe, remake the project
```
cd CPSL_TI_Radar/CPSL_TI_Radar_cpp
cd build
cmake ../
cmake --build .
```

This command will generate (2) executable files. The main one is from [main.cpp](./main.cpp) which will generate an executable called CPSL_TI_Radar_CPP.

### 3. Run the project

Finally, to run the project, perform the following command:
```
cd CPSL_TI_Radar/CPSL_TI_Radar_cpp
cd build
./CPSL_TI_Radar_CPP
```

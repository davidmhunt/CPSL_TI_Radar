# TI Radar Demo Visualizer

Add description of repository here

## Installing Dependencies
In order for the code to work properly, the following steps are required
1. Install correct version of python
2. Install CPSL_TI_Radar using Poetry

### 1. Setup Python environment
1. On ubuntu systems, start by adding the deadsnakes PPA to add the required versions of python
```
sudo add-apt-repository ppa:deadsnakes/ppa
```

2. Next, update the package list
```
sudo apt update
```
3. Finally, install python 3.10 along with the required development dependencies
```
sudo apt install python3.10 python3.10-dev
```
The following resources may be helpful [Deadsnakes PPA description](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa), [Tutorial on Deadsnakes on Ubuntu](https://preocts.github.io/python/20221230-deadsnakes/)
### 2. Install CPSL_TI_Radar using Poetry

#### Installing Poetry:
 
1. Check to see if Python Poetry is installed. If the below command is successful, poetry is installed move on to setting up the conda environment

```
    poetry --version
```
2. If Python Poetry is not installed, follow the [Poetry Install Instructions](https://python-poetry.org/docs/#installing-with-the-official-installer). On linux, Poetry can be installed using the following command:
```
curl -sSL https://install.python-poetry.org | python3 -
```

#### Installing CPSL_TI_Radar
Navigate to the CPSL_TI_Radar foler (this folder) and execute the following command

```
poetry install
```

If you get an an error saying: "Failed to unlock the collection!", execute the following command in the terminal:
```
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
```

#### Updating CPSL_TI_Radar
If the pyproject.toml file is updated, the poetry installation must also be updated. Use the following commands to update the version of poetry
```
poetry lock --no-update
poetry install
```
## Preparing the Hardware

There are two potential use cases using the CPSL_TI_Radar code. They are:
1. Streaming data from the IWR1443 demo running on the device
2. Streaming raw ADC data from the IWR1443 using the DCA1000

Depending on your use case, complete the following steps:

### Option 1: IWR1443 Demo (no DCA1000)

TO stream samples directly from the TI IWR Radar, you must flash the correct firmware onto the TI radar. To accomplish this, complete the following steps:
1. To flash the correct firmware onto the IWR1443, you will need the UNIFLASH tool from Texas Instruments. Start by downloading the correct version of the tool from the [downloads page](https://www.ti.com/tool/UNIFLASH#downloads)
2. Next, power off the IWR1443, and place it into Flashing Mode mode. Refer to the following diagram for placing the IWR in flashing mode ![IWR_SOP_Modes](readme_images/IWR_SOP_modes.png)
3. Use the Uniflash tool to install the binary located in the [firmware folder](../Firmware/IWR_Demos). Make sure you use the firmware in the IWR_Demos folder if streaming data directly from the IWR

### Option 2: IWR1443 with DCA1000

To stream samples from the DCA1000, the following steps must be completed
1. Configure your machine's I.P address for the DCA1000
2. Flash the correct firmware onto the IWR1443

#### 1.Setup Static IP Address
On your machine, configure the TCP/IPv4 to have the following settings:
1. Static IP Address
2. IP address: 192.168.33.30
3. Subnet mask: 255.255.255.0

#### 2.Flash the correct firmware onto the device
1. To flash the correct firmware onto the IWR1443, you will need the UNIFLASH tool from Texas Instruments. Start by downloading the correct version of the tool from the [downloads page](https://www.ti.com/tool/UNIFLASH#downloads)
2. Next, power off the IWR1443, and place it into Flashing Mode mode. Refer to the following diagram for placing the IWR in flashing mode ![IWR_SOP_Modes](readme_images/IWR_SOP_modes.png)
3. Use the Uniflash tool to install the binary located in the [firmware folder](../Firmware/DCA1000_Streaming). Make sure you use the firmware in the IWR_Demos folder if streaming data directly from the IWR

The hardware should now be ready to use

## Specifying Radar Configuration and Settings
Prior to running the radar/streaming samples, two key files must be updated. These are:
1. CPSL_TI_Radar_settings.json: specifies all key settings for running the code
2. radar ".cfg" file: specifies the configuration of the TI IWR radar for FMCW operation

The following sections describe how to configure both files

### 1. CPSL_TI_Radar_settings.json
The CPSL_TI_Radar_settings.json file is used to configure all of the code used to interface with either the DCA1000 or IWR1443. The main sections of the .json file are described below

#### TI_Radar_Config_management
* TI_Radar_config_path: specifies the path to the IWR's .cfg file. Example files are located in the [configurations](../configurations/) folder. Be sure the choose the one corresponding to either the DCA1000, or the IWR Demo depending on your use case. 
* export_JSON_config: on True the .cfg file will be converted to an easier to read .cfg file. The file will be saved to this folder. Additionally, this .json file can also be used to configure the IWR1443 demo radar as well, but it does not currently work when configuring the IWR for DCA1000 operation
* custom_CFAR: allows easy modification of the CFAR threshold when streaming data directly from the IWR demo application.
    * Note:  DOES NOT WORK WITH DCA1000 STREAMING

#### CLI_Controller
* CLI_port: the address to the serial port used to program the IWR device. If you don't know the serial port, use the [determine_serial_ports.ipynb](utilities_and_notebooks/determine_serial_ports.ipynb) notebook to determine them. Usually the CLI port is the smaller number.

#### Streamer
This part of the JSON file determines where the data is coming from. Only one of the two options should be enabled.
* serial_streaming: use this when streaming directly from the IWR demo application
* DCA1000_streaming: use this when streaming from the DCA1000

#### Processor: 
This part of the json addresses how the raw data is processed

* enable_plotting: if not using ROS or another outside visualization technique, set this to true to view the streamed data on the device
* save_plots_as_gif: if streaming a scatter plot of detections from the IWR, set to true to save the streamed plots as a .gif.
    * NOTE: DOES NOT WORK WHEN STREAMING FROM DCA1000
* IWR_Demo_Listeners: if streaming from the IWR directly, this specifies the address and authkey that should be used to connect to the processor and receive the point cloud. 
* DCA1000_Listeners: if streaming from the DCA1000, this specifies the address, authkey, and enable status for connecting to the DCA1000 processors. Currently, the DCA1000 Processor can send the following data:
    * raw packet data - the raw packets from the DCA1000
    * Normalized range-azimuth response - the normalized range azimuth response

#### ROS/Listeners:
If using ROS nodes to connect to the Radar code, set this to true. Otherwise set it to false. To make it easier to receive the data, we provide several starter ROS nodes in associated [CPSL_TI_Radar_ROS Repository](https://github.com/davidmhunt/CPSL_TI_Radar_ROS)

### 2. Radar .cfg file

Several sample .cfg files are located in the [configurations](../configurations/) folder. For generating additional configurations, we recommend using the [TI mmWave Demo Visualizer](https://dev.ti.com/gallery/view/mmwave/mmWave_Demo_Visualizer/ver/2.1.0/). There, you can specify settings, and then use the "Save config to PC" button to download a configuration. To fully understand the configurations, please refer to the mmWave sdk documentation.

## Running the Radar

Once the .cfg and CPSL_TI_Radar_settings.json files have been updated and the hardware has been setup, run the following code to start radar operations.

```
poetry run python run_radar.py
```

### Note 1: If using ROS/Listeners

If you are using ROS nodes or other listeners, be sure to start the CPSL_TI_Radar code first and then start the listeners after that. The code will prompt you to start the listeners when required.For instructions on how to use the ROS nodes, please refer to the following repository: [CPSL_TI_Radar_ROS Repository](https://github.com/davidmhunt/CPSL_TI_Radar_ROS)

### Note 2: custom settings.json file

If you are using a different settings.json file or are using a file from another path, use the following command to start radar operations

```
poetry run python run_radar.py SETTINGS_PATH
```

where SETTINGS_PATH is the path to the new settings.json file

## Streaming data to ROS

### Option 1: IWR1443 Demo (No DCA1000)

If you setup the IWR1443 to run the demo, follow these directions to obtain pointcloud data from the radar board

### Option 2: IWR1443 with DCA1000 

If you setup the IWR1443 and DCA1000 to support raw data streaming over ethernet, follow these directions to obtain the raw data and other processed data from the DCA1000 in ROS

#### 1. Add radar ROS package into catkin workspace

1. Copy the radar ros package folder into your current catkin workspace

2. Navigate to your catkin directory and source the setup.bash file for your catkin workspace using the following code
```
cd ~/catkin_ws
source devel/setup.bash
```
3. Run catkin_make to make the newly added radar package
```
catkin_make
```

#### 2. Run code with ROS





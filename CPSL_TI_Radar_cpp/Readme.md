# CPSL_TI_RADAR C++ code

## Installation instructions

## Install pre-requisite pakages

For help with building using cmake, use the following [tutorial](https://cmake.org/cmake/help/latest/guide/tutorial/index.html)

Build the project
```
cd build
cmake ../
cmake --build .
```

Run the project
```
./CPSL_TI_Radar_CPP
```

## Preparing the Hardware

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
# TI Radar Demo Visualizer

Add description of repository here

## Installation
In order for the code to work properly, the following steps are required
1. Setup Conda Environment
2. Install CPSL_TI_Radar using Poetry
3. Run CPSL_TI_Radar

### 1. Setup Conda Environment
1. If you haven't done so already, install Anaconda using this [User Guide](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html)

2. We have provided a .yaml file that will install all of the necessary dependencies to run the code. 

```
conda env create --file environment.yaml
```

This will create a new conda environment called: "TI_Radar_GUI". Note: If you have already created this environment and need to update it, the following command can be added

```
conda env update --file  environment.yaml --prune
```

### Installing Poetry:
 
1. Check to see if Python Poetry is installed. If the below command is successful, poetry is installed move on to setting up the conda environment

```
    poetry --version
```
2. If Python Poetry is not installed, follow the [Poetry Install Instructions](https://python-poetry.org/docs/#installing-with-the-official-installer). On linux, Poetry can be installed using the following command:
```
curl -sSL https://install.python-poetry.org | python3 -
```

### Installing CPSL_TI_Radar
Navigate to the CPSL_TI_Radar foler (this folder) and execute the following command

```
poetry install
```

If you get an an error saying: "Failed to unlock the collection!", execute the following command in the terminal:
```
export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
```

## Preparing the Hardware

There are two potential use cases using the CPSL_TI_Radar code. They are:
1. Streaming data from the IWR1443 demo running on the device
2. Streaming raw ADC data from the IWR1443 using the DCA1000

Depending on your use case, complete the following steps:

### Option 1: IWR1443 Demo (no DCA1000)

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
2. Next, power off the IWR1443, and place it into Flashing Mode mode. Refer to the following diagram for placing the IWR in flashing mode ![IWR_SOP_Modes](/Python_Modules/CPSL_TI_Radar/readme_images/IWR_SOP_modes.png)
3. Use the Uniflash tool to install the binary located in TI_Radar_Demo_Visualizer/Firmware/DCA 1000 CLI Streaming/iwr_raw_rosnode/xwr14xx_lvds_stream.bin

The hardware should now be ready to use

## Running the Radar





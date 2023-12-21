# Re-programming the DCA1000 to simultaneously connect to multiple DCA1000's

Below is a detailed set of instructions for configuring the DCA1000, particularly in the case of simultaneous 

## Getting Started
Here is some helpful information regarding the default setup of the DCA1000

### Default Network Configuration
By default, the DCA1000 operates with the following connectivity parameters:
* FPGA IP: 192.168.33.180
* FPGA MAC: 12-34-56-78-90-12
* System IP: 192.168.33.30
* Configuration port: 4096
* Data Port 4098

#### Connecting to the DCA1000
When connecting your machine to the DCA1000, you need to set your computer's ethernet configuration to have a static IPV4 address with the following properties:
* IP Address: 192.168.33.30 (or whatever the DCA1000 system IP has been set to)
* Netmask: 255.255.255.0

## DCA1000 Ethernet Configuration Switch

There are two potential ways that the DCA1000 can load in an ethernet configuration. The mode is set by manually using SW2.6 (pin6 and pin11) on the DCA1000 (pictured below)
1. **Default FPGA** (SW2.6 in postion 11): When the switch is in this configuration, the DCA1000 will load the default network configuration listed above, regardless of whether or not a new configuration has been set in the eeprom. When saving a new network configuration in the eeprom, it is helpful to place the DCA1000 in this mode as it will load the default configuration.
2. **eeprom** (SW2.6 in position 6): When the switch is in this position, the DCA1000 will load the network configuration saved in the eeprom memory. See below for instructions on how to save a new configuration using the DCA1000 CLI code.

![DCA1000 Hardware Switch](./README_images/DCA_%20mode_switch.png)

## Saving New Network Configuration using DCA1000EVM CLI
Below is a simplified set of instructions for installing and using the DCA1000EVM CLI. For more detailed instructions and reference see the [Developer Guide](./Docs/TI_DCA1000EVM_CLI_Software_DeveloperGuide.pdf) and the [User Guide](./Docs/TI_DCA1000EVM_CLI_Software_UserGuide.pdf). 

### Instalation
To install the DCA1000EVM CLI, run the following commands
```
cd SourceCode
make
```
This will create a new folder in the SourceCode directory called Release which will have the compiled binaries used to run the DCA1000EVM

### Configuring EEPROM

Once the DCA1000EVM CLI has been installed, the following instructions can be followed to set a new system ip address on the system.

1. **Load default networking configuration**: On the DCA1000, make sure that SW2.6 is set to pin 11, power cycle the board to ensure that the default network parameters are set. Once, this is done, make sure that your computer's ethernet port has a static ipv4 address set with the configuration described above. 

2. **JSON config file**: DCA1000EVM CLI uses a .json file to connect to and configure the DCA1000. Several files are already defined in the [SourceCode](./SourceCode/) directory. THe basic structure is as follows:
```
{
    
    "DCA1000Config": {
        "dataLoggingMode": "raw",
        "dataTransferMode": "LVDSCapture",
        "dataCaptureMode": "ethernetStream",
        "lvdsMode": 1,
        "dataFormatMode": 1,
        "packetDelay_us": 25,
        "ethernetConfig": {
            "DCA1000IPAddress": "192.168.33.180",
            "DCA1000ConfigPort": 4096,
            "DCA1000DataPort": 4098
            },
        "ethernetConfigUpdate": {
            "systemIPAddress": "192.168.1.100",
            "DCA1000IPAddress": "192.168.1.180",
            "DCA1000MACAddress":
            "12.34.56.78.90.12",
            "DCA1000ConfigPort": 4096,
            "DCA1000DataPort": 4098
            }
    }
}
```
Here, the ethernetConfig key defines the current network configuration being used by the DCA1000 and the "ethernetConfigUpdate" lists the new settings that you wish to use on the board. When defining a new ethernet configuration, keep the following tips in mind: 
* **System + DCA IP Address**: Through experimentation, I found that things work best when both the DCA and system IP addresses have the same XX (where the IP address is defined as 192.168.XX.YY)
* Multiple DCA1000 Tips
    * **Ethernet Port & USB Ethernet**: In this case, you need to make sure that the Ethernet Port and the USB Ethernet ports have different static system IP-addresses. However, since the netmask is 255.255.255.0, you need to make sure that the two ports have different XX values where the system IP address is defined as 192.168.XX.YY.
    * **Network Switches**: If using a network switch, you want to make sure that the DCA1000s use the same system IP address but different DCA1000 IP addresses. As such, the system IP address should be the same for both boards, but the DCA1000 IP address, Config Port, and Data Port should be different.

3. **Check Connection**: A helpful command to check that everythign is setup correctly is the fpga_version command. This can be done using the following terminal commands (replase config.json with the configuration file you defined in the previous step):
```
cd Release
./DCA1000EVM_CLI_Control fpga_version ../config.json
```
If you get an error regarding the libRF_API.so file, see the troubleshooting section for how to address this. 

4. **Program the eeprom**: To program the eeprom, use the following command (replace config.json with the config file created in step 2):
```
./DCA1000EVM_CLI_Control eeprom ../config.json
```
The command should print out: "EEPROM Configuration command: Success"

5. **Reboot and Connect with new settings**
To start using the DCA1000 with the new configuration, power off the DCA1000, set SW2.6 to position 6, and then power on the board. You will also have to modify your computer's system ip address to be the same as the one that you chose when setting the new system IP address on the DCA1000. 

6. [optional] **Check successful connection** If you want to make sure that everything loaded okay, you can define a new .json config and then re-run the fpga_version command with that new configuration. If the command successfully returns the FPGA configuration, the DCA1000 has been configured correctly. 

### Trouble Shooting
Here is are few common errors that I experienced along with solutions for how to fix them.

#### error while loading shared libraries: libRF_API.so

This error is caused when the LD_LIBRARY_PATH variable does not contain the Release folder. To add it, use the following command (all one line). Here, replace "/home/david/CPSL_TI_Radar" with the path to the directory stored on your machine.
```
export LD_LIBRARY_PATH= $LD_LIBRARY_PATH:/home/david/CPSL_TI_Radar/DCA_Programming/SourceCode/Release/
```
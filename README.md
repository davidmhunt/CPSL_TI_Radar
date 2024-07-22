# CPSL_TI_Radar Python Repository

This repo includes the CPSL_TI_Radar Python Module, the required firmware, and configurations for interfacing with the TI IWRs and TI DCA1000 data capture card. There is also additional software that can be used to re-configure the DCA1000's ethernet network configuration so as to operate multiple radar's simultaneously.

To get started, please see the following readme files:
* [CPSL TI Radar](./CPSL_TI_Radar/README.md): readme for connecting to and directly obtaining data from the TI IWR boards using TI's mMWave SDK
* [CPSL TI Radar cpp](./CPSL_TI_Radar_cpp/): readme for connecting to and directly obtaining raw data from an TI IWR using TI's DCA1000 (currently only the TI-IWR1443 Boost is supported).
* [DCA_Programming](./DCA_Programming/README.md):readme for re-programming the DCA1000's ethernet network configuration.


## ROS Integration:
In addition to this code base, the CPSL has also developed a ROS1 library for interacting with both the DCA1000 and the IWR1443 boards. If you're interested in using this code base, please see the corresponding github repository here: [CPSL_TI_Radar_ROS](https://github.com/davidmhunt/CPSL_TI_Radar_ROS)
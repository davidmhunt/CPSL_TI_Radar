# TI Radar Demo Visualizer

Add description of repository here

## Installation
In order for the code to work properly, the following steps are required
1. Setup Conda Environment
2. Install ROS
3. Add radar package to ROS src directory

### 1. Setup Conda Environment
1. If you haven't done so already, install Anaconda using this [User Guide](https://docs.conda.io/projects/conda/en/latest/user-guide/install/index.html)

2. We have provided a .yaml file that will install all of the necessary dependencies to run the code. 

```
conda env create -f TI_Radar_Demo_Visualizer/Radar/environment.yaml
```

This will create a new conda environment called: "TI_Radar_GUI". Note: If you have already created this environment and need to update it, the following command can be added

```
conda env update -f  TI_Radar_Demo_Visualizer/Radar/environment.yaml --prune
```

### 2. Install ROS
1. Follow the instructions on the [ROS installation instructions](http://wiki.ros.org/noetic/Installation) website to install ROS. If you are unfamiliar with ROS, its worth taking some of the [ROS Tutorials](http://wiki.ros.org/ROS/Tutorials)

### 3. Add Radar Package to ROS src directory
1. In order to run the ROS, the "radar" ROS package must be copied into an existing ROS catkin workspace (See [this tutorial](http://wiki.ros.org/ROS/Tutorials/InstallingandConfiguringROSEnvironment) for how to create one). If using a terminal, this can be done using the following terminal commands (assuming an existing folder isn't already there)
```
cp -r TI_Radar_Demo_Visualizer/ROS Packages/radar ~/[catkin_ws]/src
```
where [catkin_ws] is the path to an existing catkin workspace
2. To confirm that everything is working correctly, go back to the main catkin workspace directory and run catkin_make
```
cd ~/[catkin_ws]
catkin_make
```

## Setting Up Code
### 1. Specify Serial Ports
1. Specify serial ports in the "TI_Radar_Demo_Visualizer/config_Radar.json" file. The file determine_serial_ports.ipynb can be used to determine the correct serial ports on your machine

### 2. Configure Correct ROS Frame
The radar is mounted on a drone based platform. Additionally, we use a VICOM system to provide ground truth information for the rotation/position of the drone and objects in the scene. To setup the ROS node correctly, complete the following instructions

1. In the "TI_Radar_Demo_Visualizer/ROS Packages/radar/scripts/radar_static_transform.py", change the frame_id to be the frame_ID of the reference frame of the drone (or other platform)
```
static_transformStamped.header.frame_id = "[Drone Frame ID]"
```
For example, you could set [Drone Frame ID] to be "vicon/Drone1/Drone1"

## Running Code
Running the code is performed in several steps. Here, it is recommended  to use a tool that allows you to display multiple tmux windows simultaneously. The following sets of instructions should be performed in order and in separate terminals:
1. Start roscore
2. Start Vicom rosnodes
3. Start Radar python module
4. Start Radar rosnodes
5. Perform visualization in ROS using rviz

### 1. Start roscore

1. In a new terminal window, perform the following command
```
roscore
```

### 2. Start Vicom Rosnodes
1. Add text on how to start the rosnodes

### 3. Start Radar python module
1. In a new terminal window, navigate to the directory with radar code in it
```
cd TI_Radar_Demo_Visualizer/Radar
```
2. In the config_Radar.json file, ensure that ROS is enabled
3. Activate the conda environment using
```
conda activate TI_Radar_GUI
```
4. Start the radar module
```
python3 Radar.py
```
The radar module should now be running, and should be waiting on the line: "Radar.start_Radar:waiting for TLV listeners to connect to ROS clients"

### 4. Start Radar rosnodes
The rosnodes that integrate with the radar and initialize the coordinate frame for the radar can be launched simulatneously. 
1. In a new terminal, ensure that conda is deactivated
```
conda deactivate
```
2. Launch the ROS nodes for radar operation
```
roslaunch radar start_radar_nodes.launch
```

### 5. Visualize the radar operation using RVIZ
1. To visualize the environment and the radar data, use rviz which can be launched using 
```
conda deactivate
rosrun rviz rviz
```
If you get an error, make sure that conda is deactivated as sometimes it will cause errors
2. To visualize the scene, we have implemented a simple rviz setup which can be loaded using the "rviz_config.rviz" file. The vicom system visualizations and reference frames must be set for this to work correctly 
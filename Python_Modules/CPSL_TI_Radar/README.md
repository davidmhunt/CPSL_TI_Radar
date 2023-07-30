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
conda env create -f TI_Radar_Demo_Visualizer/Radar/environment.yaml
```

This will create a new conda environment called: "TI_Radar_GUI". Note: If you have already created this environment and need to update it, the following command can be added

```
conda env update -f  TI_Radar_Demo_Visualizer/Radar/environment.yaml --prune
```


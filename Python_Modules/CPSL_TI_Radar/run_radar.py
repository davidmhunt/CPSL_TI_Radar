from CPSL_TI_Radar.Radar import Radar
import sys


def main():
    radar = Radar("/home/david/Documents/TI_Radar_Demo_Visualizer/Python_Modules/CPSL_TI_Radar/CPSL_TI_Radar_settings.json")
    radar.run(timeout=20)

#create the controller object
if __name__ == '__main__':
    main()
    sys.exit()
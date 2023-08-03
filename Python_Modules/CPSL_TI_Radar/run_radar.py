from CPSL_TI_Radar.Radar import Radar
import argparse
import sys


def main(settings_path):
    radar = Radar(settings_path)
    radar.run(timeout=20)

#create the controller object
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        'settings_path',
          type=str, nargs='?',
            default='/home/david/Documents/TI_Radar_Demo_Visualizer/Python_Modules/CPSL_TI_Radar/CPSL_TI_Radar_settings.json',
              help='path to settings file')
    args = parser.parse_args()

    main(args.settings_path)
    sys.exit()
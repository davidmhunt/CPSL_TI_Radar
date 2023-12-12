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
        '--json_config',
        type=str,
        default='json_radar_settings/radar_1.json',
        help='path to settings file')
    args = parser.parse_args()

    main(args.settings_path)
    sys.exit()
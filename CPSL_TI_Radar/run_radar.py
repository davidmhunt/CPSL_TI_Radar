from CPSL_TI_Radar.Radar import Radar
import argparse
import sys
import os


def main(json_config):
    json_config = os.path.join("json_radar_settings",json_config)
    radar = Radar(json_config)
    radar.run(timeout=20)

#create the controller object
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--json_config',
        type=str,
        default='radar_1.json',
        help='path to settings file')
    args = parser.parse_args()

    main(args.json_config)
    sys.exit()